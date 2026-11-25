"""Testy backendu PyMuPDF: ścieżki → model pośredni."""

from __future__ import annotations

import pymupdf
import pytest

from conftest import MakePdf
from pdf2dxf.backends import open_pdf
from pdf2dxf.backends.pymupdf_backend import items_to_subpaths, parse_dashes, to_rgb
from pdf2dxf.model import DashPattern, LineSeg


def _extract(pdf, index: int = 0):
    with open_pdf(pdf) as backend:
        return backend.extract_page(index)


def test_line(make_pdf: MakePdf) -> None:
    page = _extract(make_pdf(lambda p: p.draw_line((100, 100), (200, 100))))
    assert (page.width, page.height, page.rotation) == (595, 842, 0)
    assert len(page.shapes) == 1
    shape = page.shapes[0]
    assert shape.stroked and not shape.filled
    assert len(shape.subpaths) == 1
    sp = shape.subpaths[0]
    assert sp.segments == [LineSeg((100.0, 100.0), (200.0, 100.0))]
    assert not sp.closed


def test_rect_closed_four_segments(make_pdf: MakePdf) -> None:
    page = _extract(make_pdf(lambda p: p.draw_rect(pymupdf.Rect(50, 200, 150, 260))))
    sp = page.shapes[0].subpaths[0]
    assert sp.closed and len(sp.segments) == 4
    assert set(sp.points()) == {(50, 200), (150, 200), (150, 260), (50, 260)}
    assert sp.start == sp.end


def test_rect_orientation_counterclockwise_on_screen() -> None:
    # orientacja 1 = jak operator PDF "re": lewy dolny → prawy dolny → prawy górny
    (sp,) = items_to_subpaths([("re", pymupdf.Rect(10, 140, 60, 190), 1)])
    assert sp.points() == [(10, 190), (60, 190), (60, 140), (10, 140), (10, 190)]
    (sp,) = items_to_subpaths([("re", pymupdf.Rect(10, 140, 60, 190), -1)])
    assert sp.points() == [(10, 190), (10, 140), (60, 140), (60, 190), (10, 190)]


def test_quad_perimeter_order() -> None:
    quad = pymupdf.Quad((10, 0), (20, 10), (0, 10), (10, 20))  # ul, ur, ll, lr (romb)
    (sp,) = items_to_subpaths([("qu", quad)])
    assert sp.closed
    assert sp.points() == [(10, 0), (20, 10), (10, 20), (0, 10), (10, 0)]


def test_disjoint_items_split_into_subpaths() -> None:
    items = [
        ("l", (0, 0), (10, 0)),
        ("l", (10, 0), (10, 10)),
        ("l", (50, 50), (60, 50)),
    ]
    subpaths = items_to_subpaths(items)
    assert [len(s.segments) for s in subpaths] == [2, 1]
    assert not any(s.closed for s in subpaths)


def test_closed_by_geometry_and_snapped() -> None:
    items = [("l", (0, 0), (10, 0)), ("l", (10, 0), (5, 8)), ("l", (5, 8), (0.0004, 0.0002))]
    (sp,) = items_to_subpaths(items)
    assert sp.closed
    assert sp.end == sp.start == (0, 0)


def test_close_path_flag_adds_closing_segment() -> None:
    items = [("l", (0, 0), (10, 0)), ("l", (10, 0), (5, 8))]
    (sp,) = items_to_subpaths(items, close_path=True)
    assert sp.closed and len(sp.segments) == 3
    assert sp.segments[-1] == LineSeg((5, 8), (0, 0))


def test_polyline_closed_in_pdf(make_pdf: MakePdf) -> None:
    def draw(page: pymupdf.Page) -> None:
        sh = page.new_shape()
        sh.draw_polyline([(10, 10), (100, 10), (60, 80)])
        sh.finish(closePath=True, color=(0, 0, 0))
        sh.commit()

    sp = _extract(make_pdf(draw)).shapes[0].subpaths[0]
    assert sp.closed and len(sp.segments) == 3


def test_style_basic(make_pdf: MakePdf) -> None:
    page = _extract(make_pdf(lambda p: p.draw_line((0, 0), (10, 0), color=(1, 0, 0), width=2)))
    style = page.shapes[0].style
    assert style.stroke_color == (1.0, 0.0, 0.0)
    assert style.line_width == 2.0
    assert style.dashes is None
    assert style.layer is None


@pytest.mark.parametrize(("value", "expected"), [
    (None, None),
    ("[] 0", None),
    ("[ 6 3 ] 0", DashPattern((6.0, 3.0), 0.0)),
    ("[2 1 0.5 1] 1.5", DashPattern((2.0, 1.0, 0.5, 1.0), 1.5)),
    ("[ 3 ] 0", DashPattern((3.0, 3.0), 0.0)),
    ("[0 0] 0", None),
])
def test_parse_dashes(value: str | None, expected: DashPattern | None) -> None:
    assert parse_dashes(value) == expected


@pytest.mark.parametrize(("value", "expected"), [
    (None, None),
    ((0.5,), (0.5, 0.5, 0.5)),
    ((1, 0, 0), (1.0, 0.0, 0.0)),
    ((0, 0, 0, 1), (0.0, 0.0, 0.0)),
    ((1, 0, 0, 0), (0.0, 1.0, 1.0)),
])
def test_to_rgb(value, expected) -> None:
    assert to_rgb(value) == expected


def test_render_png_fits_box(make_pdf: MakePdf) -> None:
    pdf = make_pdf(lambda p: p.draw_rect(pymupdf.Rect(50, 50, 200, 100)), rotation=90)
    with open_pdf(pdf) as backend:
        png = backend.render_png(0, 400, 300)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pix = pymupdf.Pixmap(png)
    # strona obrócona: widok 842×595 (poziomy) — dopasowany do 400×300
    assert pix.width <= 400 and pix.height <= 300 and pix.width > pix.height
