"""Funkcje pomocnicze testów."""

from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf.document import Drawing

from pdf2dxf.converter import ConversionReport, ConvertOptions, convert

MM_PER_PT = 25.4 / 72.0


def read_dxf(path: Path) -> Drawing:
    """Otwiera DXF ponownie i sprawdza, że audyt nie zgłasza błędów ani poprawek (test 14)."""
    doc = ezdxf.readfile(path)
    auditor = doc.audit()
    assert not auditor.has_errors, [str(e.message) for e in auditor.errors]
    assert not auditor.has_fixes, [str(f.message) for f in auditor.fixes]
    return doc


def convert_one(pdf: Path, **options: object) -> tuple[ConversionReport, Drawing]:
    """Konwertuje PDF do jednego pliku DXF obok niego i zwraca (raport, dokument)."""
    out = pdf.with_suffix(".dxf")
    report = convert(pdf, out, ConvertOptions(**options))  # type: ignore[arg-type]
    assert report.outputs == [out]
    return report, read_dxf(out)
