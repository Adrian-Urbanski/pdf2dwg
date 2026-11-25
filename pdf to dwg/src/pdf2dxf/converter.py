"""Potok konwersji PDF → DXF: wybór stron, ekstrakcja, transformacja, zapis.

Moduł spina pozostałe warstwy i jest wspólny dla CLI (oraz ewentualnego GUI).
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pdf2dxf.backends import PdfError, open_pdf
from pdf2dxf.model import PageData
from pdf2dxf.postprocess import PostprocessOptions, merge_texts, postprocess_page
from pdf2dxf.transform import page_transform, transform_page
from pdf2dxf.writer import DxfWriter, WriterOptions

log = logging.getLogger(__name__)

PAGE_GAP = 0.1
"""Odstęp między stronami w trybie --single-file (ułamek szerokości strony)."""
RASTER_MIN_COVERAGE = 0.3
"""Minimalny ułamek strony zakryty obrazami, by uznać ją za skan."""
RASTER_MAX_VECTOR_ITEMS = 5
"""Maksymalna liczba podścieżek + fragmentów tekstu na stronie uznanej za skan."""


class ConversionError(Exception):
    """Błąd konwersji (kod wyjścia 1)."""


class UsageError(Exception):
    """Niepoprawne parametry wywołania wykryte dopiero po otwarciu PDF (kod 2)."""


@dataclass
class ConvertOptions:
    """Wszystkie opcje konwersji (odpowiadają opcjom CLI)."""

    pages: list[int] | None = None
    single_file: bool = False
    units: str = "mm"
    scale: float = 1.0
    curves: str = "spline"
    flatten_tol: float = 0.01
    detect_arcs: bool = True
    join: bool = False
    layers: str = "by-color"
    fills: str = "hatch"
    text: bool = True
    merge_text: bool = False
    text_height_factor: float = 0.7
    dxf_version: str = "R2010"
    preview: bool = False
    dwg: bool = False
    dwg_version: str = "R2018"
    oda_path: str | None = None

    def writer_options(self) -> WriterOptions:
        return WriterOptions(
            units=self.units,
            dxf_version=self.dxf_version,
            curves=self.curves,
            flatten_tol_mm=self.flatten_tol,
            layers=self.layers,
            fills=self.fills,
            text_height_factor=self.text_height_factor,
        )


@dataclass
class PageReport:
    """Wynik konwersji jednej strony."""

    number: int
    output: Path | None = None
    entities: Counter[str] = field(default_factory=Counter)
    duplicates_removed: int = 0
    joined: int = 0
    warnings: list[str] = field(default_factory=list)
    raster: bool = False
    empty: bool = False

    @property
    def skipped(self) -> bool:
        """Strona pominięta (skan albo brak danych wektorowych)."""
        return self.raster or self.empty


@dataclass
class ConversionReport:
    """Wynik całej konwersji."""

    input: Path
    pages: list[PageReport] = field(default_factory=list)
    outputs: list[Path] = field(default_factory=list)
    previews: list[Path] = field(default_factory=list)
    dwg_outputs: list[Path] = field(default_factory=list)
    dwg_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def no_vector_data(self) -> bool:
        """Żadna strona nie miała danych wektorowych (np. sam skan)."""
        return bool(self.pages) and all(p.skipped for p in self.pages)

    @property
    def looks_scanned(self) -> bool:
        """Co najmniej jedna strona wygląda na skan."""
        return any(p.raster for p in self.pages)


def resolve_output(input_path: Path, output: str | Path | None) -> tuple[Path, str]:
    """Zwraca (katalog, rdzeń nazwy) plików wynikowych.

    ``output`` może być: ``None`` (obok PDF), katalogiem (istniejącym albo
    zakończonym separatorem) lub ścieżką pliku ``.dxf``.
    """
    if output is None:
        return input_path.parent, input_path.stem
    text = str(output)
    path = Path(text)
    if text.endswith(("/", "\\")) or path.is_dir():
        return path, input_path.stem
    stem = path.stem if path.suffix.lower() == ".dxf" else path.name
    return path.parent, stem


def output_file(directory: Path, stem: str, page_number: int | None) -> Path:
    """Nazwa pliku: ``stem.dxf`` albo ``stem_pN.dxf`` przy wielu plikach."""
    suffix = "" if page_number is None else f"_p{page_number}"
    return directory / f"{stem}{suffix}.dxf"


def select_pages(requested: list[int] | None, page_count: int) -> tuple[list[int], list[str]]:
    """Wybiera numery stron (od 1). Zwraca (strony, ostrzeżenia)."""
    if page_count == 0:
        raise ConversionError("PDF nie zawiera żadnych stron")
    if not requested:
        return list(range(1, page_count + 1)), []
    valid = [n for n in requested if n <= page_count]
    missing = [n for n in requested if n > page_count]
    warnings = []
    if missing:
        warnings.append(
            f"pominięto nieistniejące strony: {', '.join(map(str, missing))} "
            f"(dokument ma {page_count})"
        )
    if not valid:
        raise UsageError(f"żadna z podanych stron nie istnieje (dokument ma {page_count} stron)")
    return valid, warnings


def convert(
    input_path: str | Path,
    output: str | Path | None = None,
    options: ConvertOptions | None = None,
) -> ConversionReport:
    """Konwertuje PDF do jednego lub wielu plików DXF."""
    opts = options or ConvertOptions()
    src = Path(input_path)
    if not src.is_file():
        raise ConversionError(f"nie znaleziono pliku: {src}")
    report = ConversionReport(input=src)
    directory, stem = resolve_output(src, output)

    try:
        backend = open_pdf(src)
    except PdfError as exc:
        raise ConversionError(str(exc)) from exc

    with backend:
        numbers, warnings = select_pages(opts.pages, backend.page_count)
        report.warnings.extend(warnings)
        one_file = opts.single_file or len(numbers) == 1
        writer = DxfWriter(opts.writer_options()) if one_file else None
        written = 0
        x_offset = 0.0
        for number in numbers:
            page = backend.extract_page(number - 1, with_text=opts.text)
            page_report = PageReport(number=number, warnings=list(page.warnings))
            report.pages.append(page_report)
            if not _check_content(page, page_report):
                continue
            tr = page_transform(page, opts.units, opts.scale, offset=(x_offset, 0.0))
            dxf_page = transform_page(page, tr)
            if opts.merge_text:
                dxf_page.texts = merge_texts(dxf_page.texts)
            dxf_page, stats = postprocess_page(
                dxf_page, PostprocessOptions(detect_arcs=opts.detect_arcs, join=opts.join)
            )
            page_report.duplicates_removed = stats.duplicates_removed
            page_report.joined = stats.joined
            if one_file:
                assert writer is not None
                page_report.entities = writer.add_page(dxf_page)
                x_offset += dxf_page.width * (1.0 + PAGE_GAP)
                written += 1
            else:
                single = DxfWriter(opts.writer_options())
                page_report.entities = single.add_page(dxf_page)
                path = output_file(directory, stem, number)
                _save(single, path)
                page_report.output = path
                report.outputs.append(path)
        if one_file and written:
            assert writer is not None
            path = output_file(directory, stem, None)
            _save(writer, path)
            for pr in report.pages:
                if not pr.skipped:
                    pr.output = path
            report.outputs.append(path)
    if opts.preview:
        _make_previews(report)
    if opts.dwg:
        _make_dwg(report, opts)
    return report


def _make_dwg(report: ConversionReport, opts: ConvertOptions) -> None:
    """Konwertuje zapisane pliki DXF do DWG; błędy trafiają do ``report.dwg_errors``."""
    from pdf2dxf.dwg import ConverterNotFound, DwgError, dxf_to_dwg

    for path in report.outputs:
        try:
            report.dwg_outputs.append(
                dxf_to_dwg(path, version=opts.dwg_version, converter=opts.oda_path)
            )
        except ConverterNotFound as exc:
            report.dwg_errors.append(str(exc))
            return
        except DwgError as exc:
            report.dwg_errors.append(str(exc))


def _make_previews(report: ConversionReport) -> None:
    """Renderuje podgląd PNG dla każdego zapisanego pliku DXF (błędy → ostrzeżenia)."""
    from pdf2dxf.preview import PreviewUnavailable, render_preview

    for path in report.outputs:
        try:
            report.previews.append(render_preview(path))
        except PreviewUnavailable as exc:
            report.warnings.append(str(exc))
            return
        except Exception as exc:  # podgląd nie może zepsuć samej konwersji
            log.debug("podgląd %s nie powiódł się", path, exc_info=True)
            report.warnings.append(f"nie udało się utworzyć podglądu {path.name}: {exc}")


def has_vectors(page: PageData) -> bool:
    """Czy strona ma jakąkolwiek geometrię lub tekst."""
    return bool(page.shapes or page.texts)


def is_raster_page(page: PageData) -> bool:
    """Strona wygląda na skan: obraz zakrywający znaczną część strony i prawie brak wektorów."""
    if page.image_count == 0:
        return False
    vector_items = sum(len(s.subpaths) for s in page.shapes) + len(page.texts)
    return page.image_coverage >= RASTER_MIN_COVERAGE and vector_items <= RASTER_MAX_VECTOR_ITEMS


def _check_content(page: PageData, page_report: PageReport) -> bool:
    """Klasyfikuje stronę; zwraca False, gdy ma być pominięta."""
    if is_raster_page(page):
        page_report.raster = True
        page_report.warnings.append(
            "strona wygląda na skan (obraz bez danych wektorowych) — pominięta"
        )
        return False
    if not has_vectors(page):
        page_report.empty = True
        page_report.warnings.append("strona nie zawiera danych wektorowych — pominięta")
        return False
    if page.image_count:
        page_report.warnings.append(
            f"strona zawiera obrazy ({page.image_count}) — obrazy nie są przenoszone do DXF"
        )
    return True


def _save(writer: DxfWriter, path: Path) -> None:
    try:
        writer.save(path)
    except OSError as exc:
        raise ConversionError(f"nie można zapisać {path}: {exc}") from exc
