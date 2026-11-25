"""Backendy ekstrakcji PDF."""

from __future__ import annotations

from pathlib import Path

from pdf2dxf.backends.base import PdfBackend, PdfError

__all__ = ["PdfBackend", "PdfError", "open_pdf"]


def open_pdf(path: str | Path) -> PdfBackend:
    """Otwiera PDF domyślnym backendem (PyMuPDF)."""
    from pdf2dxf.backends.pymupdf_backend import PyMuPdfBackend

    return PyMuPdfBackend(Path(path))
