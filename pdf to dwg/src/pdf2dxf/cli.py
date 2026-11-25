"""Interfejs wiersza poleceń: argumenty, raport, kody wyjścia."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from pdf2dxf import __version__
from pdf2dxf.converter import ConversionError, ConversionReport, ConvertOptions, UsageError, convert
from pdf2dxf.dwg import DWG_VERSIONS
from pdf2dxf.dwg import ENV_VAR as ODA_ENV_VAR

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_NO_VECTORS = 3

UNITS = ("mm", "cm", "m", "in", "pt")
DXF_VERSIONS = ("R2000", "R2004", "R2007", "R2010", "R2013", "R2018")


def parse_pages(spec: str) -> list[int]:
    """Zamienia zapis typu ``"1,3-5"`` na posortowaną listę numerów stron (od 1).

    Raises:
        argparse.ArgumentTypeError: gdy zapis jest niepoprawny.
    """
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                start_s, end_s = part.split("-", 1)
                start, end = int(start_s), int(end_s)
                if start > end:
                    raise ValueError
                pages.update(range(start, end + 1))
            else:
                pages.add(int(part))
        except ValueError:
            raise argparse.ArgumentTypeError(f"niepoprawny zakres stron: {part!r}") from None
    if not pages or min(pages) < 1:
        raise argparse.ArgumentTypeError(f"niepoprawny zakres stron: {spec!r}")
    return sorted(pages)


def _positive_float(text: str) -> float:
    try:
        value = float(text.replace(",", "."))
    except ValueError:
        raise argparse.ArgumentTypeError(f"to nie jest liczba: {text!r}") from None
    if value <= 0:
        raise argparse.ArgumentTypeError(f"wartość musi być dodatnia: {text!r}")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Buduje parser argumentów zgodny z sekcją 10 specyfikacji."""
    p = argparse.ArgumentParser(
        prog="pdf2dxf",
        description="Konwersja wektorowych rysunków PDF do DXF.",
        epilog="Kody wyjścia: 0 OK, 1 błąd, 2 złe argumenty, 3 brak danych wektorowych (skan).",
        add_help=False,
    )
    p.add_argument("-h", "--help", action="help", help="pokaż tę pomoc i zakończ")
    p.add_argument("input", metavar="INPUT.pdf", help="plik PDF do konwersji")
    p.add_argument(
        "-o", "--output", metavar="OUT",
        help="plik wynikowy .dxf albo katalog (zakończony / lub istniejący); "
             "domyślnie obok pliku PDF",
    )

    g = p.add_argument_group("strony")
    g.add_argument("--pages", type=parse_pages, metavar="1,3-5",
                   help="strony do konwersji (numeracja od 1); domyślnie wszystkie")
    g.add_argument("--single-file", action="store_true",
                   help="wszystkie strony obok siebie w jednym pliku DXF")

    g = p.add_argument_group("jednostki i skala")
    g.add_argument("--units", choices=UNITS, default="mm",
                   help="jednostki rysunku DXF (domyślnie: mm)")
    g.add_argument("--scale", type=_positive_float, default=1.0, metavar="N",
                   help="rysunek w skali 1:N — współrzędne mnożone przez N (domyślnie: 1)")

    g = p.add_argument_group("geometria")
    g.add_argument("--curves", choices=("spline", "polyline"), default="spline",
                   help="krzywe Béziera jako SPLINE albo spłaszczone LWPOLYLINE (domyślnie: spline)")
    g.add_argument("--flatten-tol", type=_positive_float, default=0.01, metavar="MM",
                   help="tolerancja spłaszczania krzywych w mm na arkuszu (domyślnie: 0.01)")
    g.add_argument("--detect-arcs", action=argparse.BooleanOptionalAction, default=True,
                   help="wykrywaj okręgi i łuki w krzywych Béziera (domyślnie: włączone)")
    g.add_argument("--join", action="store_true",
                   help="sklejaj odcinki o wspólnych końcach w polilinie")

    g = p.add_argument_group("styl")
    g.add_argument("--layers", choices=("by-color", "by-ocg", "single"), default="by-color",
                   help="podział na warstwy (domyślnie: by-color)")
    g.add_argument("--fills", choices=("hatch", "outline", "ignore"), default="hatch",
                   help="obsługa wypełnień (domyślnie: hatch)")

    g = p.add_argument_group("tekst")
    g.add_argument("--no-text", action="store_true", help="pomiń tekst")
    g.add_argument("--merge-text", action="store_true",
                   help="łącz fragmenty tekstu z jednej linii o tym samym stylu")
    g.add_argument("--text-height-factor", type=_positive_float, default=0.7, metavar="F",
                   help="wysokość TEXT = rozmiar fontu × F (domyślnie: 0.7)")

    g = p.add_argument_group("wynik")
    g.add_argument("--dxf-version", choices=DXF_VERSIONS, default="R2010",
                   help="wersja pliku DXF (domyślnie: R2010)")
    g.add_argument("--preview", action="store_true",
                   help="zapisz obok DXF podgląd PNG (wymaga matplotlib)")

    g = p.add_argument_group("DWG (wymaga ODA File Converter)")
    g.add_argument("--dwg", action="store_true",
                   help="dodatkowo zapisz DWG obok każdego DXF")
    g.add_argument("--dwg-version", choices=DWG_VERSIONS, default="R2018",
                   help="wersja pliku DWG (domyślnie: R2018)")
    g.add_argument("--oda-path", metavar="PATH",
                   help="ścieżka do ODAFileConverter(.exe) lub jego katalogu; domyślnie "
                        f"szukany automatycznie (także zmienna {ODA_ENV_VAR})")

    p.add_argument("-v", "--verbose", action="store_true", help="więcej komunikatów")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}",
                   help="pokaż wersję i zakończ")
    return p


def options_from_args(ns: argparse.Namespace) -> ConvertOptions:
    """Zamienia sparsowane argumenty na :class:`ConvertOptions`."""
    return ConvertOptions(
        pages=ns.pages,
        single_file=ns.single_file,
        units=ns.units,
        scale=ns.scale,
        curves=ns.curves,
        flatten_tol=ns.flatten_tol,
        detect_arcs=ns.detect_arcs,
        join=ns.join,
        layers=ns.layers,
        fills=ns.fills,
        text=not ns.no_text,
        merge_text=ns.merge_text,
        text_height_factor=ns.text_height_factor,
        dxf_version=ns.dxf_version,
        preview=ns.preview,
        dwg=ns.dwg,
        dwg_version=ns.dwg_version,
        oda_path=ns.oda_path,
    )


def format_report(report: ConversionReport) -> str:
    """Raport tekstowy: encje wg typu, duplikaty i ostrzeżenia dla każdej strony."""
    lines = [f"pdf2dxf: {report.input.name}"]
    for w in report.warnings:
        lines.append(f"  ostrzeżenie: {w}")
    for pr in report.pages:
        head = f"  strona {pr.number}"
        if pr.output is not None:
            head += f" → {pr.output}"
        lines.append(head)
        if pr.entities:
            counts = ", ".join(f"{name} {n}" for name, n in sorted(pr.entities.items()))
            lines.append(f"    encje: {counts} (razem {sum(pr.entities.values())})")
        elif not pr.skipped:
            lines.append("    encje: brak")
        if not pr.skipped:
            lines.append(f"    usunięte duplikaty: {pr.duplicates_removed}")
        if pr.joined:
            lines.append(f"    połączone odcinki: {pr.joined}")
        for w in pr.warnings:
            lines.append(f"    ostrzeżenie: {w}")
    for png in report.previews:
        lines.append(f"  podgląd: {png}")
    for dwg_file in report.dwg_outputs:
        lines.append(f"  DWG: {dwg_file}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Punkt wejścia CLI. Zwraca kod wyjścia."""
    parser = build_parser()
    ns = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if ns.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    _utf8_console()
    try:
        report = convert(ns.input, ns.output, options_from_args(ns))
    except UsageError as exc:
        parser.print_usage(sys.stderr)
        print(f"pdf2dxf: błąd: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except ConversionError as exc:
        print(f"pdf2dxf: błąd: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(format_report(report))
    for err in report.dwg_errors:
        print(f"pdf2dxf: błąd DWG: {err}", file=sys.stderr)
    if report.no_vector_data:
        if report.looks_scanned:
            msg = ("PDF nie zawiera danych wektorowych — wygląda na skan. Potrzebna jest "
                   "wektoryzacja (np. potrace lub dedykowany program).")
        else:
            msg = "PDF nie zawiera danych wektorowych — nie zapisano żadnego pliku."
        print(f"pdf2dxf: {msg}", file=sys.stderr)
        return EXIT_NO_VECTORS
    if report.dwg_errors:
        return EXIT_ERROR
    return EXIT_OK


def _utf8_console() -> None:
    """Znaki spoza strony kodowej konsoli (Windows) zastępuje zamiast przerywać wypisywanie."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):  # pragma: no cover
                pass
