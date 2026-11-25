"""Wspólne fixture'y: generowanie testowych PDF-ów o znanej geometrii."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pymupdf
import pytest

Draw = Callable[[pymupdf.Page], None]
MakePdf = Callable[..., Path]


def raw(stream: bytes) -> Draw:
    """Funkcja rysująca, która podmienia strumień treści strony na surowe operatory PDF.

    Uwaga: współrzędne w strumieniu są w układzie PDF (oś Y w górę).
    """

    def draw(page: pymupdf.Page) -> None:
        page.insert_text((0, 0), " ")  # tworzy strumień treści
        page.parent.update_stream(page.get_contents()[0], stream)

    return draw


@pytest.fixture
def make_pdf(tmp_path: Path) -> MakePdf:
    """Fabryka PDF-ów: każda funkcja ``draw`` rysuje jedną stronę.

    Przykład: ``make_pdf(lambda p: p.draw_line((100, 100), (200, 100)))``.
    Obrót (``rotation``) ustawiany jest *po* narysowaniu treści, więc
    współrzędne rysowania dotyczą strony nieobróconej.
    """

    def factory(
        *draws: Draw,
        name: str = "test.pdf",
        width: float = 595,
        height: float = 842,
        rotation: int = 0,
    ) -> Path:
        doc = pymupdf.open()
        for draw in draws or (lambda page: None,):
            page = doc.new_page(width=width, height=height)
            draw(page)
            if rotation:
                page.set_rotation(rotation)
        path = tmp_path / name
        doc.save(path)
        doc.close()
        return path

    return factory
