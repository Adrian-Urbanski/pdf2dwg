"""Testy funkcji pomocniczych writera (kolory, grubości, nazwy, kontury HATCH)."""

from __future__ import annotations

import pytest

from pdf2dxf.writer import (
    color_attribs,
    color_layer_name,
    hatch_boundaries,
    lineweight,
    nearest_aci,
    sanitize_layer_name,
    signed_area,
)


@pytest.mark.parametrize(("rgb", "aci"), [
    ((255, 0, 0), 1), ((255, 255, 0), 2), ((0, 255, 0), 3), ((0, 255, 255), 4),
    ((0, 0, 255), 5), ((255, 0, 255), 6), ((255, 255, 255), 7),
])
def test_nearest_aci(rgb: tuple[int, int, int], aci: int) -> None:
    assert nearest_aci(rgb) == aci


def test_color_attribs_black_is_aci7_without_true_color() -> None:
    assert color_attribs((0, 0, 0)) == {"color": 7}
    assert color_attribs((0.02, 0.01, 0.0)) == {"color": 7}
    assert color_attribs(None) == {"color": 7}
    assert color_attribs((1, 0, 0)) == {"color": 1, "true_color": 0xFF0000}


@pytest.mark.parametrize(("pt", "lw"), [(0, 0), (0.1, 5), (1, 35), (2, 70), (100, 211)])
def test_lineweight(pt: float, lw: int) -> None:
    assert lineweight(pt) == lw


def test_layer_names() -> None:
    assert color_layer_name((1, 0.5, 0)) == "PDF_FF8000"
    assert sanitize_layer_name('a<b>c/d\\e"f:g;h?i*j|k=l`m') == "a_b_c_d_e_f_g_h_i_j_k_l_m"
    assert sanitize_layer_name("Ściany żelbet") == "Ściany żelbet"
    assert sanitize_layer_name("  ") == "PDF"


SQUARE = [(0, 0), (10, 0), (10, 10), (0, 10)]          # CCW
INNER_CCW = [(2, 2), (8, 2), (8, 8), (2, 8)]
INNER_CW = list(reversed(INNER_CCW))


def test_signed_area() -> None:
    assert signed_area(SQUARE) == 100
    assert signed_area(INNER_CW) == -36


def test_hatch_boundaries_even_odd() -> None:
    out = hatch_boundaries([SQUARE, INNER_CCW], even_odd=True)
    assert [ext for _, ext in out] == [True, False]


def test_hatch_boundaries_nonzero_same_direction_drops_inner() -> None:
    out = hatch_boundaries([SQUARE, INNER_CCW], even_odd=False)
    assert [poly for poly, _ in out] == [SQUARE]


def test_hatch_boundaries_nonzero_opposite_direction_keeps_hole() -> None:
    out = hatch_boundaries([SQUARE, INNER_CW], even_odd=False)
    assert [(poly, ext) for poly, ext in out] == [(SQUARE, True), (INNER_CW, False)]


def test_hatch_boundaries_separate_islands() -> None:
    other = [(20, 0), (30, 0), (30, 10), (20, 10)]
    out = hatch_boundaries([SQUARE, other], even_odd=False)
    assert [ext for _, ext in out] == [True, True]
