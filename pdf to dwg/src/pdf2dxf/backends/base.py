"""Interfejs backendu ekstrakcji PDF.

Reszta programu korzysta wyłącznie z :class:`PdfBackend` i modelu
:mod:`pdf2dxf.model`, dzięki czemu PyMuPDF (AGPL) można podmienić na inny
backend (np. pypdfium2) bez zmian w transformacji i writerze.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from types import TracebackType

from pdf2dxf.model import PageData


class PdfError(Exception):
    """Nie da się otworzyć lub odczytać pliku PDF."""


class PdfBackend(ABC):
    """Otwarty dokument PDF, z którego wyciągamy dane stron."""

    @abstractmethod
    def __init__(self, path: Path) -> None:
        """Otwiera plik. Rzuca :class:`PdfError`, gdy to niemożliwe."""

    @property
    @abstractmethod
    def page_count(self) -> int:
        """Liczba stron dokumentu."""

    @abstractmethod
    def extract_page(self, index: int, *, with_text: bool = True) -> PageData:
        """Zwraca dane strony ``index`` (od 0) w przestrzeni PDF."""

    @abstractmethod
    def close(self) -> None:
        """Zwalnia zasoby."""

    def render_png(self, index: int, max_width: int, max_height: int) -> bytes:
        """Obraz PNG strony ``index`` (tak, jak w przeglądarce PDF), dopasowany do
        prostokąta ``max_width × max_height`` pikseli. Używany do podglądu w oknie."""
        raise NotImplementedError("ten backend nie obsługuje podglądu stron")

    def __enter__(self) -> PdfBackend:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
