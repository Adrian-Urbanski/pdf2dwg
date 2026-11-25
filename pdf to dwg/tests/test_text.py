"""Faza 3: tekst (ekstrakcja, kąt, polskie znaki, łączenie spanów)."""

from __future__ import annotations

from collections.abc import Callable

import pymupdf
import pytest

from conftest import MakePdf
from helpers import convert_one
from pdf2dxf.backends import open_pdf
from pdf2dxf.model import TextItem
from pdf2dxf.postprocess import merge_texts

MM = 25.4 / 72
POLISH = "Zażółć gęślą jaźń"


def _with_font(fn: Callable[[pymupdf.Page], None]) -> Callable[[pymupdf.Page], None]:
    """Rejestruje na stronie font Unicode (Noto Sans z pymupdf-fonts) jako 'notos'."""

    def draw(page: pymupdf.Page) -> None:
        page.insert_font(fontname="notos", fontbuffer=pymupdf.Font("notos").buffer)
        fn(page)

    return draw


def _text_pdf(make_pdf: MakePdf, **kw) -> pymupdf.Page:
    return make_pdf(_with_font(
        lambda p: p.insert_text((50, 150), POLISH, fontname="notos", fontsize=12, **kw)))


def test_case5_polish_text_roundtrip(make_pdf: MakePdf) -> None:
    report, doc = convert_one(_text_pdf(make_pdf))
    assert report.pages[0].entities == {"TEXT": 1}
    (text,) = doc.modelspace().query("TEXT")
    assert text.dxf.text == POLISH
    assert (text.dxf.insert.x, text.dxf.insert.y) == pytest.approx((50 * MM, (842 - 150) * MM))
    assert text.dxf.height == pytest.approx(12 * MM * 0.7)
    assert text.dxf.rotation == pytest.approx(0)
    assert text.dxf.style == "PDF_TEXT"
    assert doc.styles.get("PDF_TEXT").dxf.font == "arial.ttf"
    assert text.dxf.color == 7


def test_text_height_factor_and_scale(make_pdf: MakePdf) -> None:
    _, doc = convert_one(_text_pdf(make_pdf), text_height_factor=1.0, scale=50)
    (text,) = doc.modelspace().query("TEXT")
    assert text.dxf.height == pytest.approx(12 * MM * 50)


def test_text_color_and_layer(make_pdf: MakePdf) -> None:
    _, doc = convert_one(_text_pdf(make_pdf, color=(1, 0, 0)))
    (text,) = doc.modelspace().query("TEXT")
    assert text.rgb == (255, 0, 0)
    assert text.dxf.layer == "PDF_FF0000"


def test_no_text(make_pdf: MakePdf) -> None:
    def draw(page: pymupdf.Page) -> None:
        page.insert_text((50, 150), POLISH, fontname="notos", fontsize=12)
        page.draw_line((10, 10), (100, 10))

    report, doc = convert_one(make_pdf(_with_font(draw)), text=False)
    assert not doc.modelspace().query("TEXT")
    assert report.pages[0].entities == {"LINE": 1}


def test_rotated_text_90(make_pdf: MakePdf) -> None:
    _, doc = convert_one(_text_pdf(make_pdf, rotate=90))
    (text,) = doc.modelspace().query("TEXT")
    assert text.dxf.rotation == pytest.approx(90)
    assert (text.dxf.insert.x, text.dxf.insert.y) == pytest.approx((50 * MM, (842 - 150) * MM))


def test_rotated_text_30_degrees(make_pdf: MakePdf) -> None:
    def draw(page: pymupdf.Page) -> None:
        p0 = pymupdf.Point(250, 400)
        # morph obraca tekst o 30° w lewo (przeciwnie do wskazówek zegara na ekranie)
        page.insert_text(p0, "Kąt 30", fontname="notos", fontsize=10,
                         morph=(p0, pymupdf.Matrix(-30)))

    _, doc = convert_one(make_pdf(_with_font(draw)))
    (text,) = doc.modelspace().query("TEXT")
    assert text.dxf.text == "Kąt 30"
    assert text.dxf.rotation == pytest.approx(330, abs=0.01)  # = −30°
    assert (text.dxf.insert.x, text.dxf.insert.y) == pytest.approx(
        (250 * MM, (842 - 400) * MM), abs=1e-3)


def test_text_on_rotated_page(make_pdf: MakePdf) -> None:
    pdf = make_pdf(_with_font(
        lambda p: p.insert_text((100, 200), "Rot", fontname="notos", fontsize=12)), rotation=90)
    _, doc = convert_one(pdf)
    (text,) = doc.modelspace().query("TEXT")
    # strona 595×842 obrócona o 90° (w prawo): widok 842×595, tekst biegnie w dół
    assert text.dxf.rotation == pytest.approx(270)
    assert (text.dxf.insert.x, text.dxf.insert.y) == pytest.approx(
        ((842 - 200) * MM, (595 - 100) * MM))


def test_invisible_text_skipped_with_warning(make_pdf: MakePdf) -> None:
    def draw(page: pymupdf.Page) -> None:
        page.insert_text((50, 100), "Widoczny", fontsize=12)
        page.insert_text((50, 200), "Niewidoczny", fontsize=12, render_mode=3)

    report, doc = convert_one(make_pdf(draw))
    assert [t.dxf.text for t in doc.modelspace().query("TEXT")] == ["Widoczny"]
    assert any("niewidocznych" in w for w in report.pages[0].warnings)


def _two_words(gap: float):
    def draw(page: pymupdf.Page) -> None:
        width = pymupdf.Font("helv").text_length("Abc", 12)
        page.insert_text((50, 100), "Abc", fontsize=12)
        page.insert_text((50 + width + gap, 100), "Def", fontsize=12)
    return draw


def test_spans_separate_without_merge(make_pdf: MakePdf) -> None:
    _, doc = convert_one(make_pdf(_two_words(4)))
    assert sorted(t.dxf.text for t in doc.modelspace().query("TEXT")) == ["Abc", "Def"]


def test_merge_text(make_pdf: MakePdf) -> None:
    _, doc = convert_one(make_pdf(_two_words(4)), merge_text=True)
    (text,) = doc.modelspace().query("TEXT")
    assert text.dxf.text == "Abc Def"
    assert text.dxf.insert.x == pytest.approx(50 * MM)


def test_merge_text_keeps_distant_words(make_pdf: MakePdf) -> None:
    _, doc = convert_one(make_pdf(_two_words(30)), merge_text=True)
    assert sorted(t.dxf.text for t in doc.modelspace().query("TEXT")) == ["Abc", "Def"]


def test_span_width_estimated(make_pdf: MakePdf) -> None:
    pdf = make_pdf(_two_words(30))
    with open_pdf(pdf) as backend:
        texts = backend.extract_page(0).texts
    expected = pymupdf.Font("helv").text_length("Abc", 12)
    assert texts[0].width == pytest.approx(expected, abs=0.5)


def test_merge_texts_rules() -> None:
    a = TextItem("Ab", (0, 0), 10, angle=0, width=10)
    b = TextItem("cd", (10.5, 0), 10, angle=0, width=10)        # styk → bez spacji
    c = TextItem("ef", (23, 0), 10, angle=0, width=10)          # przerwa 2.5 → spacja
    d = TextItem("gh", (60, 0), 10, angle=0, width=10)          # za daleko
    e = TextItem("ij", (70, 5), 10, angle=0, width=10)          # inna linia bazowa
    out = merge_texts([a, b, c, d, e])
    assert [t.text for t in out] == ["Abcd ef", "gh", "ij"]
    assert out[0].width == pytest.approx(33)
    rot = [TextItem("A", (0, 0), 10, angle=90, width=5), TextItem("B", (0, 5), 10, angle=90,
                                                                   width=5)]
    assert [t.text for t in merge_texts(rot)] == ["AB"]
    red = TextItem("x", (11, 0), 10, angle=0, width=5, color=(1, 0, 0))
    assert len(merge_texts([a, red])) == 2
