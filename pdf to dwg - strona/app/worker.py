"""Konwersja jednego zadania — uruchamiana w osobnym procesie: ``python -m app.worker KATALOG``.

Osobny proces izoluje serwer od trudnych plików (pamięć, zawieszenie, awaria
biblioteki) i pozwala go zabić po przekroczeniu limitu czasu.

Wejście: ``KATALOG/job.json`` i ``KATALOG/input.pdf``. Wyjście: ``KATALOG/result.json``,
pliki wynikowe w ``KATALOG/out/`` i (gdy jest ich kilka) ``KATALOG/<nazwa>.zip``,
podgląd pierwszej strony ``KATALOG/preview.png``.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import traceback
import zipfile
from pathlib import Path
from typing import Any

from pdf2dxf.backends import PdfError, open_pdf
from pdf2dxf.converter import ConversionError, ConvertOptions, UsageError, convert

PREVIEW_SIZE = 480
COMMAND_TIMEOUT = 300


class JobError(Exception):
    """Błąd pokazywany użytkownikowi."""


TOO_COMPLEX = "plik jest zbyt złożony (zabrakło pamięci) — spróbuj z mniejszą liczbą stron"


def _clean(message: str, job_dir: Path) -> str:
    """Usuwa ścieżki serwera z komunikatu dla użytkownika (także w zapisie z ``\\\\``)."""
    for base in (job_dir / "out", job_dir):
        for text in (str(base) + os.sep, str(base)):
            message = message.replace(text, "").replace(text.replace("\\", "\\\\"), "")
    return message


def _pdf_error_message(exc: PdfError) -> str:
    """Komunikat bez ścieżek i szczegółów biblioteki dla pliku, którego nie da się otworzyć."""
    text = str(exc)
    if "hasłem" in text:
        return "PDF jest zabezpieczony hasłem — zapisz go bez hasła i spróbuj ponownie"
    if "nie jest dokumentem PDF" in text:
        return "to nie jest plik PDF"
    return "nie można odczytać pliku — PDF jest uszkodzony albo niepełny"


def _is_out_of_memory(exc: BaseException) -> bool:
    text = str(exc).lower()
    return isinstance(exc, MemoryError) or "malloc" in text or "out of memory" in text


def _lower_priority() -> None:
    """Linux: konwersja ustępuje serwerowi WWW procesorem, a przy braku pamięci jądro
    zabija ją przed serwerem (oom_score_adj). Na innych systemach nic nie robi."""
    if not sys.platform.startswith("linux"):
        return
    try:
        os.nice(10)
    except OSError:
        pass
    try:
        Path("/proc/self/oom_score_adj").write_text("1000", encoding="ascii")
    except OSError:
        pass


def _dxf_to_dwg(dxf: Path, version: str, engine: dict[str, Any]) -> Path:
    """Konwertuje DXF → DWG wybranym silnikiem; zwraca ścieżkę DWG."""
    dwg = dxf.with_suffix(".dwg")
    if engine["name"] == "oda":
        from pdf2dxf.dwg import dxf_to_dwg

        return dxf_to_dwg(dxf, dwg, version=version, converter=engine.get("oda_path"))
    if engine["name"] == "command":
        template = shlex.split(engine["command"], posix=os.name != "nt")
        if os.name == "nt":  # shlex w trybie nie-POSIX zostawia cudzysłowy w argumentach
            template = [p[1:-1] if len(p) > 1 and p[0] == p[-1] == '"' else p for p in template]
        args = [part.format(input=str(dxf), output=str(dwg), version=version) for part in template]
        proc = subprocess.run(args, capture_output=True, text=True, timeout=COMMAND_TIMEOUT,
                              errors="replace")
        if proc.returncode != 0 or not dwg.is_file() or dwg.stat().st_size == 0:
            detail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["brak pliku DWG"]
            raise RuntimeError(f"konwersja {dxf.name} do DWG nie powiodła się: {detail[0]}")
        return dwg
    raise RuntimeError("zapis DWG jest wyłączony na serwerze")


def _render_preview(src: Path, page_index: int, dest: Path) -> None:
    try:
        with open_pdf(src) as backend:
            dest.write_bytes(backend.render_png(page_index, PREVIEW_SIZE, PREVIEW_SIZE))
    except Exception:  # podgląd jest dodatkiem — nie może zepsuć konwersji
        traceback.print_exc()


def run_job(job_dir: Path) -> dict[str, Any]:
    spec = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    stem: str = spec["stem"]
    convert_opts: dict[str, Any] = spec["options"]["convert"]
    fmt: str = spec["options"]["format"]
    dwg_version: str = spec["options"]["dwg_version"]
    src = job_dir / "input.pdf"

    try:
        with open_pdf(src) as backend:
            page_count = backend.page_count
    except PdfError as exc:
        raise JobError(_pdf_error_message(exc)) from exc
    if page_count == 0:
        raise JobError("PDF nie zawiera żadnych stron")
    requested = convert_opts.get("pages")
    selected = [p for p in requested if p <= page_count] if requested else list(
        range(1, page_count + 1))
    if not selected:
        raise JobError(f"żadna z wybranych stron nie istnieje (dokument ma {page_count} str.)")
    if len(selected) > spec["max_pages"]:
        raise JobError(
            f"dokument ma {page_count} stron, a jednorazowo można przekonwertować "
            f"{spec['max_pages']} — wpisz zakres stron w opcjach (np. 1-{spec['max_pages']})"
        )
    _render_preview(src, selected[0] - 1, job_dir / "preview.png")

    out_dir = job_dir / "out"
    out_dir.mkdir(exist_ok=True)
    try:
        report = convert(src, out_dir / f"{stem}.dxf", ConvertOptions(**convert_opts))
    except (ConversionError, UsageError) as exc:
        raise JobError(_clean(str(exc), job_dir)) from exc

    warnings = [_clean(w, job_dir) for w in report.warnings]
    pages = []
    for page in report.pages:
        pages.append({
            "number": page.number,
            "skipped": page.skipped,
            "raster": page.raster,
            "entities": dict(sorted(page.entities.items())),
            "total": sum(page.entities.values()),
            "duplicates_removed": page.duplicates_removed,
            "joined": page.joined,
            "warnings": [_clean(w, job_dir) for w in page.warnings],
        })
    if report.no_vector_data:
        message = ("PDF wygląda na skan (obraz bez linii wektorowych) — taki plik wymaga "
                   "wektoryzacji, której ten konwerter nie robi"
                   if report.looks_scanned else "PDF nie zawiera rysunku wektorowego")
        return {"ok": False, "error": message, "pages": pages, "warnings": warnings,
                "page_count": page_count}

    files: list[Path] = []
    for dxf in report.outputs:
        if fmt == "dwg":
            try:
                files.append(_dxf_to_dwg(dxf, dwg_version, spec["engine"]))
                dxf.unlink(missing_ok=True)
                continue
            except Exception as exc:  # DWG się nie udał — oddajemy przynajmniej DXF
                traceback.print_exc()
                warnings.append(
                    f"nie udało się zapisać DWG ({_clean(str(exc), job_dir)}) — "
                    f"w zamian plik DXF, który otworzy każdy program CAD"
                )
        files.append(dxf)

    if len(files) > 1:
        bundle = job_dir / f"{stem}.zip"
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in files:
                zf.write(path, path.name)
        download = bundle
    else:
        download = files[0]
    return {
        "ok": True,
        "page_count": page_count,
        "pages": pages,
        "warnings": warnings,
        "files": [{"name": p.name, "size": p.stat().st_size} for p in files],
        "download": {"name": download.name, "size": download.stat().st_size,
                     "path": str(download.relative_to(job_dir))},
    }


def main(argv: list[str]) -> int:
    job_dir = Path(argv[1]).resolve()
    _lower_priority()
    try:
        result = run_job(job_dir)
    except JobError as exc:
        result = {"ok": False, "error": str(exc)}
    except Exception as exc:
        traceback.print_exc()
        result = {"ok": False, "error": TOO_COMPLEX if _is_out_of_memory(exc) else
                  "nieoczekiwany błąd konwersji — ten plik nie dał się przetworzyć"}
    tmp = job_dir / "result.json.tmp"
    tmp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    tmp.replace(job_dir / "result.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
