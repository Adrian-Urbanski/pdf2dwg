"""Faza 2: krzywe, kolory, grubości, warstwy, linie przerywane, wypełnienia (PDF → DXF)."""

from __future__ import annotations

import math

import pymupdf
import pytest

from conftest import MakePdf, raw
from helpers import convert_one

MM = 25.4 / 72


def _xy(pt_pdf: tuple[float, float], height: float = 842) -> tuple[float, float]:
    return (pt_pdf[0] * MM, (height - pt_pdf[1]) * MM)


def _circle(page: pymupdf.Page) -> None:
    page.draw_circle((300, 300), 50, color=(0, 0, 1))


# --- test 3 (bez wykrywania okręgów) -----------------------------------------


def test_case3_circle_as_spline(make_pdf: MakePdf) -> None:
    _, doc = convert_one(make_pdf(_circle), detect_arcs=False)
    msp = doc.modelspace()
    (spline,) = msp.query("SPLINE")
    assert not msp.query("LINE LWPOLYLINE CIRCLE")
    ctrl = spline.control_points
    assert tuple(ctrl[0][:2]) == pytest.approx(_xy((250, 300)))
    assert tuple(ctrl[-1][:2]) == pytest.approx(_xy((250, 300)))
    center = _xy((300, 300))
    for p in spline.construction_tool().flattening(0.01):
        assert math.dist((p.x, p.y), center) == pytest.approx(50 * MM, abs=0.01)


def test_case3_circle_as_polyline(make_pdf: MakePdf) -> None:
    _, doc = convert_one(make_pdf(_circle), detect_arcs=False, curves="polyline", flatten_tol=0.01)
    msp = doc.modelspace()
    (pl,) = msp.query("LWPOLYLINE")
    assert pl.closed and len(pl) > 16
    assert not msp.query("SPLINE")
    center = _xy((300, 300))
    r = 50 * MM
    bezier_err = r * 3e-4  # 4 krzywe Béziera przybliżają okrąg z błędem ~0.027 %
    pts = [(x, y) for x, y, *_ in pl.get_points()]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        assert math.dist(a, center) == pytest.approx(r, abs=bezier_err)
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        assert r - math.dist(mid, center) <= 0.01 + bezier_err  # cięciwa w tolerancji


# --- test 4 -------------------------------------------------------------------


def test_case4_bezier_spline_endpoints(make_pdf: MakePdf) -> None:
    pdf = make_pdf(lambda p: p.draw_bezier((50, 400), (100, 350), (150, 450), (200, 400)))
    _, doc = convert_one(pdf)
    (spline,) = doc.modelspace().query("SPLINE")
    ctrl = spline.control_points
    assert len(ctrl) == 4
    assert tuple(ctrl[0][:2]) == pytest.approx(_xy((50, 400)))
    assert tuple(ctrl[1][:2]) == pytest.approx(_xy((100, 350)))
    assert tuple(ctrl[-1][:2]) == pytest.approx(_xy((200, 400)))
    assert spline.dxf.degree == 3


def _mixed(close: bool):
    def draw(page: pymupdf.Page) -> None:
        sh = page.new_shape()
        sh.draw_line((10, 10), (100, 10))
        sh.draw_bezier((100, 10), (150, 10), (150, 60), (100, 60))
        sh.draw_line((100, 60), (10, 60))
        sh.finish(color=(0, 0, 0), closePath=close)
        sh.commit()
    return draw


def test_mixed_path_lines_and_curve(make_pdf: MakePdf) -> None:
    report, _ = convert_one(make_pdf(_mixed(close=False)))
    assert report.pages[0].entities == {"LINE": 2, "SPLINE": 1}


def test_closed_mixed_path_merges_line_runs(make_pdf: MakePdf) -> None:
    # zamknięcie dodaje odcinek (10,60)-(10,10); linie przed i za punktem startu
    # tworzą jedną polilinię zamiast LINE + LWPOLYLINE
    report, doc = convert_one(make_pdf(_mixed(close=True)), detect_arcs=False)
    assert report.pages[0].entities == {"LWPOLYLINE": 1, "SPLINE": 1}
    (pl,) = doc.modelspace().query("LWPOLYLINE")
    assert len(pl) == 4 and not pl.closed


# --- test 6: kolory i warstwy ---------------------------------------------------


def test_case6_red_and_black(make_pdf: MakePdf) -> None:
    def draw(page: pymupdf.Page) -> None:
        page.draw_line((10, 10), (100, 10), color=(1, 0, 0))
        page.draw_line((10, 20), (100, 20), color=(0, 0, 0))

    _, doc = convert_one(make_pdf(draw))
    red, black = sorted(doc.modelspace().query("LINE"), key=lambda e: -e.dxf.start.y)
    assert red.rgb == (255, 0, 0)
    assert red.dxf.layer == "PDF_FF0000"
    assert red.dxf.color == 1
    assert black.dxf.color == 7
    assert not black.has_dxf_attrib("true_color")
    assert black.dxf.layer == "PDF_000000"
    assert doc.layers.get("PDF_FF0000").dxf.color == 1


def test_layers_single(make_pdf: MakePdf) -> None:
    pdf = make_pdf(lambda p: p.draw_line((10, 10), (100, 10), color=(1, 0, 0)))
    _, doc = convert_one(pdf, layers="single")
    (line,) = doc.modelspace().query("LINE")
    assert line.dxf.layer == "PDF"
    assert line.rgb == (255, 0, 0)


def test_layers_by_ocg_with_fallback(make_pdf: MakePdf) -> None:
    def draw(page: pymupdf.Page) -> None:
        ocg = page.parent.add_ocg("Ściany: nośne")
        page.draw_line((10, 10), (100, 10), oc=ocg)
        page.draw_line((10, 20), (100, 20), color=(0, 0, 1))

    _, doc = convert_one(make_pdf(draw), layers="by-ocg")
    layers = sorted(e.dxf.layer for e in doc.modelspace().query("LINE"))
    assert layers == ["PDF_0000FF", "Ściany_ nośne"]


def test_lineweight(make_pdf: MakePdf) -> None:
    # PyMuPDF draw_line(width=0) zapisuje domyślną grubość, więc surowy strumień:
    # 1 pt → 0.353 mm → 0.35;  0.5 pt → 0.176 mm → 0.18;  0 (najcieńsza) → 0.00
    stream = b"1 w 10 830 m 100 830 l S 0.5 w 10 820 m 100 820 l S 0 w 10 810 m 100 810 l S"
    _, doc = convert_one(make_pdf(raw(stream)))
    lines = sorted(doc.modelspace().query("LINE"), key=lambda e: -e.dxf.start.y)
    assert [e.dxf.lineweight for e in lines] == [35, 18, 0]
    assert doc.header["$LWDISPLAY"] == 1


def test_transparency(make_pdf: MakePdf) -> None:
    pdf = make_pdf(lambda p: p.draw_line((10, 10), (100, 10), stroke_opacity=0.5))
    _, doc = convert_one(pdf)
    (line,) = doc.modelspace().query("LINE")
    assert line.transparency == pytest.approx(0.5, abs=0.01)


def _kitchen_sink(page: pymupdf.Page) -> None:
    page.draw_line((100, 100), (200, 100), color=(1, 0, 0))
    page.draw_rect(pymupdf.Rect(50, 200, 150, 260))
    page.draw_circle((300, 300), 50, color=(0, 0, 1))
    page.draw_bezier((50, 400), (100, 350), (150, 450), (200, 400), color=(0, 0.5, 0))
    page.draw_line((50, 500), (250, 500), dashes="[6 3] 0", width=0.7)
    page.draw_rect(pymupdf.Rect(300, 450, 400, 500), color=None, fill=(0, 0, 1))
    page.draw_rect(pymupdf.Rect(420, 450, 520, 500), color=(1, 0, 0), fill=(1, 1, 0),
                   fill_opacity=0.5)


@pytest.mark.parametrize("version", ["R2000", "R2004", "R2007", "R2010", "R2013", "R2018"])
@pytest.mark.parametrize("curves", ["spline", "polyline"])
def test_case14_all_versions_audit_clean(make_pdf: MakePdf, version: str, curves: str) -> None:
    report, doc = convert_one(make_pdf(_kitchen_sink), dxf_version=version, curves=curves)
    assert sum(report.pages[0].entities.values()) >= 8
    assert len(doc.modelspace()) == sum(report.pages[0].entities.values())


# --- test 8: linie przerywane -----------------------------------------------------


def test_case8_dashed_line_linetype(make_pdf: MakePdf) -> None:
    def draw(page: pymupdf.Page) -> None:
        page.draw_line((50, 500), (250, 500), dashes="[6 3] 0")
        page.draw_line((50, 510), (250, 510), dashes="[6 3] 0")
        page.draw_line((50, 520), (250, 520), dashes="[2 2] 0")
        page.draw_line((50, 530), (250, 530))

    _, doc = convert_one(make_pdf(draw))
    lines = sorted(doc.modelspace().query("LINE"), key=lambda e: -e.dxf.start.y)
    names = [e.dxf.linetype for e in lines]
    assert names[0] == names[1] != names[2]
    assert names[3] == "BYLAYER"
    tags = doc.linetypes.get(names[0]).pattern_tags.tags
    total = [t.value for t in tags if t.code == 40]
    elements = [t.value for t in tags if t.code == 49]
    assert total == pytest.approx([9 * MM])
    assert elements == pytest.approx([6 * MM, -3 * MM])
    assert len([n for n in doc.linetypes if n.dxf.name.startswith("PDF_DASH")]) == 2


# --- test 9: wypełnienia ---------------------------------------------------------


def _filled_rect(page: pymupdf.Page) -> None:
    page.draw_rect(pymupdf.Rect(300, 450, 400, 500), color=None, fill=(0, 0, 1))


def test_case9_filled_rect_hatch(make_pdf: MakePdf) -> None:
    report, doc = convert_one(make_pdf(_filled_rect))
    msp = doc.modelspace()
    (hatch,) = msp.query("HATCH")
    assert report.pages[0].entities == {"HATCH": 1}
    assert hatch.dxf.solid_fill == 1
    assert hatch.dxf.pattern_name == "SOLID"
    assert hatch.rgb == (0, 0, 255)
    assert hatch.dxf.layer == "PDF_0000FF"
    (path,) = hatch.paths
    assert len(path.vertices) == 4


def test_fill_and_stroke(make_pdf: MakePdf) -> None:
    pdf = make_pdf(lambda p: p.draw_rect(pymupdf.Rect(10, 10, 50, 50), color=(1, 0, 0),
                                         fill=(1, 1, 0)))
    report, doc = convert_one(pdf)
    assert report.pages[0].entities == {"HATCH": 1, "LWPOLYLINE": 1}
    entities = list(doc.modelspace())
    assert [e.dxftype() for e in entities] == ["HATCH", "LWPOLYLINE"]  # obrys nad wypełnieniem
    assert entities[0].rgb == (255, 255, 0) and entities[1].rgb == (255, 0, 0)


def test_fills_outline_and_ignore(make_pdf: MakePdf) -> None:
    pdf = make_pdf(_filled_rect)
    report, doc = convert_one(pdf, fills="outline")
    assert report.pages[0].entities == {"LWPOLYLINE": 1}
    (pl,) = doc.modelspace().query("LWPOLYLINE")
    assert pl.closed and pl.rgb == (0, 0, 255)
    report, doc = convert_one(pdf, fills="ignore")
    assert not report.pages[0].entities


def test_white_background_skipped(make_pdf: MakePdf) -> None:
    def draw(page: pymupdf.Page) -> None:
        page.draw_rect(page.rect, color=None, fill=(1, 1, 1))
        page.draw_rect(pymupdf.Rect(10, 10, 50, 50), color=None, fill=(1, 1, 1))  # nie tło
        page.draw_line((10, 100), (100, 100))

    report, _ = convert_one(make_pdf(draw))
    assert report.pages[0].entities == {"HATCH": 1, "LINE": 1}


def _two_rects(even_odd: bool, same_direction: bool):
    def draw(page: pymupdf.Page) -> None:
        sh = page.new_shape()
        sh.draw_rect(pymupdf.Rect(100, 100, 300, 300))
        inner = [(150, 150), (250, 150), (250, 250), (150, 250)]
        if same_direction:  # draw_rect: ten sam obieg co zewnętrzny
            sh.draw_rect(pymupdf.Rect(150, 150, 250, 250))
        else:
            sh.draw_polyline(inner)
        sh.finish(fill=(0, 0, 0), color=None, even_odd=even_odd, closePath=True)
        sh.commit()
    return draw


@pytest.mark.parametrize(("even_odd", "same_direction", "expected_paths"), [
    (True, True, 2),     # even-odd: zawsze dziura
    (False, True, 1),    # nonzero, ten sam obieg: brak dziury
    (False, False, 2),   # nonzero, przeciwny obieg: dziura
])
def test_hatch_holes(make_pdf: MakePdf, even_odd: bool, same_direction: bool,
                     expected_paths: int) -> None:
    _, doc = convert_one(make_pdf(_two_rects(even_odd, same_direction)))
    (hatch,) = doc.modelspace().query("HATCH")
    assert len(hatch.paths) == expected_paths
    assert hatch.dxf.hatch_style == 0
