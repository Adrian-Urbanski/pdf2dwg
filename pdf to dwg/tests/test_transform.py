"""Testy transformacji współrzędnych i jednostek."""

from __future__ import annotations

import pymupdf
import pytest

from pdf2dxf.model import LineSeg, PageData, Shape, Style, SubPath, TextItem
from pdf2dxf.transform import (
    Affine,
    make_transform,
    rotated_size,
    rotation_matrix,
    transform_page,
)

MM = 25.4 / 72


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotation_matrix_matches_pymupdf(rotation: int) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.set_rotation(rotation)
    ref = page.rotation_matrix
    ours = rotation_matrix(595, 842, rotation)
    assert (ours.a, ours.b, ours.c, ours.d, ours.e, ours.f) == pytest.approx(
        (ref.a, ref.b, ref.c, ref.d, ref.e, ref.f)
    )
    assert rotated_size(595, 842, rotation) == (page.rect.width, page.rect.height)


def test_affine_then() -> None:
    m = Affine(2, 0, 0, 2, 1, 1).then(Affine(1, 0, 0, -1, 0, 10))
    assert m.apply((3, 4)) == (7, 10 - 9)


def test_point_mm_and_y_flip() -> None:
    tr = make_transform(595, 842)
    x, y = tr.point((100, 100))
    assert x == pytest.approx(100 * MM)
    assert y == pytest.approx((842 - 100) * MM)
    assert tr.width == pytest.approx(595 * MM) and tr.height == pytest.approx(842 * MM)


@pytest.mark.parametrize(("units", "factor"), [
    ("mm", 25.4 / 72), ("cm", 2.54 / 72), ("m", 0.0254 / 72), ("in", 1 / 72), ("pt", 1.0),
])
def test_units(units: str, factor: float) -> None:
    assert make_transform(595, 842, units=units).k == pytest.approx(factor)


def test_scale_multiplies_coordinates() -> None:
    tr = make_transform(595, 842, scale=100)
    assert tr.k == pytest.approx(100 * MM)
    assert tr.point((0, 842)) == pytest.approx((0, 0))


def test_offset() -> None:
    tr = make_transform(100, 100, units="pt", offset=(1000, 5))
    assert tr.point((0, 100)) == pytest.approx((1000, 5))


def test_rotation_90_top_left_goes_to_top_right() -> None:
    # Strona 595×842 obrócona o 90° jest widoczna jako 842×595 (pozioma).
    tr = make_transform(595, 842, rotation=90, units="pt")
    assert (tr.width, tr.height) == (842, 595)
    # lewy górny róg nieobróconej strony → prawy górny róg widoku
    assert tr.point((0, 0)) == pytest.approx((842, 595))
    assert tr.point((100, 100)) == pytest.approx((742, 495))


@pytest.mark.parametrize(("rotation", "pdf_angle", "expected"), [
    (0, 0, 0),
    (0, -90, 90),       # tekst „do góry” (dir = (0, -1))
    (0, 30, -30),
    (90, 0, -90),       # strona obrócona w prawo obraca też tekst
    (180, 0, 180),
    (270, 0, 90),
])
def test_angle(rotation: int, pdf_angle: float, expected: float) -> None:
    tr = make_transform(595, 842, rotation=rotation)
    assert tr.angle(pdf_angle) == pytest.approx(expected)


def test_transform_page() -> None:
    page = PageData(
        index=0, width=200, height=100, rotation=0,
        shapes=[Shape([SubPath([LineSeg((0, 0), (200, 0))])], Style(line_width=2))],
        texts=[TextItem("A", (10, 50), 12, angle=0)],
    )
    out = transform_page(page, make_transform(200, 100, units="pt", scale=2))
    assert out.space == "dxf" and out.unit_scale == 2
    assert (out.width, out.height) == (400, 200)
    assert out.shapes[0].subpaths[0].segments[0] == LineSeg((0, 200), (400, 200))
    assert out.shapes[0].style.line_width == 2  # grubość bez zmian (pt)
    assert out.texts[0].origin == (20, 100) and out.texts[0].size == 24
    assert page.space == "pdf"  # oryginał nietknięty
    with pytest.raises(ValueError):
        transform_page(out, make_transform(200, 100))
