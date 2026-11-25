"""Faza 4: postprocessing — deduplikacja, okręgi i łuki, łączenie odcinków."""

from __future__ import annotations

import math

import pymupdf
import pytest

from conftest import MakePdf
from helpers import convert_one
from pdf2dxf.model import ArcSeg, CubicSeg, LineSeg, PageData, Shape, Style, SubPath
from pdf2dxf.postprocess import (
    PostprocessOptions,
    cubic_to_arc,
    deduplicate,
    join_subpaths,
    merge_arcs,
    postprocess_page,
    remove_zero_length,
    round_shape,
)

MM = 25.4 / 72


def _xy(p: tuple[float, float], height: float = 842) -> tuple[float, float]:
    return (p[0] * MM, (height - p[1]) * MM)


# --- test 3 (pełny): okrąg ----------------------------------------------------------


def _circle(page: pymupdf.Page) -> None:
    page.draw_circle((300, 300), 50)


def test_case3_circle_detected(make_pdf: MakePdf) -> None:
    report, doc = convert_one(make_pdf(_circle))
    assert report.pages[0].entities == {"CIRCLE": 1}
    (circle,) = doc.modelspace().query("CIRCLE")
    assert circle.dxf.radius == pytest.approx(17.639, abs=1e-3)
    assert (circle.dxf.center.x, circle.dxf.center.y) == pytest.approx(_xy((300, 300)), abs=1e-6)


def test_case3_circle_variants(make_pdf: MakePdf) -> None:
    pdf = make_pdf(_circle)
    assert convert_one(pdf, detect_arcs=False)[0].pages[0].entities == {"SPLINE": 1}
    assert convert_one(pdf, detect_arcs=False, curves="polyline")[0].pages[0].entities == {
        "LWPOLYLINE": 1}
    # wykrywanie łuków ma pierwszeństwo przed --curves polyline (CIRCLE jest dokładny)
    assert convert_one(pdf, curves="polyline")[0].pages[0].entities == {"CIRCLE": 1}


def test_ellipse_is_not_a_circle(make_pdf: MakePdf) -> None:
    pdf = make_pdf(lambda p: p.draw_oval(pymupdf.Rect(400, 100, 500, 150)))
    assert convert_one(pdf)[0].pages[0].entities == {"SPLINE": 1}


def test_quarter_arc(make_pdf: MakePdf) -> None:
    def draw(page: pymupdf.Page) -> None:
        sh = page.new_shape()
        sh.draw_sector((300, 400), (350, 400), 90, fullSector=False)
        sh.finish(color=(0, 0, 0), closePath=False)
        sh.commit()

    report, doc = convert_one(make_pdf(draw))
    assert report.pages[0].entities == {"ARC": 1}
    (arc,) = doc.modelspace().query("ARC")
    assert arc.dxf.radius == pytest.approx(50 * MM)
    assert (arc.dxf.center.x, arc.dxf.center.y) == pytest.approx(_xy((300, 400)), abs=1e-6)
    assert (arc.dxf.start_angle, arc.dxf.end_angle) == pytest.approx((0, 90), abs=1e-6)


def test_half_circle_clockwise_merged_into_one_arc(make_pdf: MakePdf) -> None:
    def draw(page: pymupdf.Page) -> None:
        sh = page.new_shape()
        sh.draw_sector((300, 600), (350, 600), -180, fullSector=False)
        sh.finish(color=(0, 0, 0), closePath=False)
        sh.commit()

    report, doc = convert_one(make_pdf(draw))
    assert report.pages[0].entities == {"ARC": 1}
    (arc,) = doc.modelspace().query("ARC")
    # łuk biegnie na ekranie w dół — w DXF (oś Y w górę) to dolna połówka: 180° → 360°
    assert arc.dxf.start_angle == pytest.approx(180, abs=1e-6)
    assert arc.dxf.end_angle % 360 == pytest.approx(0, abs=1e-6)


def test_rounded_rect_as_bulge_polyline(make_pdf: MakePdf) -> None:
    pdf = make_pdf(lambda p: p.draw_rect(pymupdf.Rect(100, 100, 300, 200), radius=0.2))
    report, doc = convert_one(pdf)
    assert report.pages[0].entities == {"LWPOLYLINE": 1}
    (pl,) = doc.modelspace().query("LWPOLYLINE")
    assert pl.closed and len(pl) == 8
    bulges = sorted(abs(b) for *_, b in pl.get_points("xyb"))
    assert bulges[:4] == pytest.approx([0, 0, 0, 0])
    assert bulges[4:] == pytest.approx([math.tan(math.radians(22.5))] * 4, abs=1e-6)


def test_filled_circle_hatch_uses_exact_bulges(make_pdf: MakePdf) -> None:
    pdf = make_pdf(lambda p: p.draw_circle((300, 300), 50, color=None, fill=(1, 0, 0)))
    _, doc = convert_one(pdf)
    (hatch,) = doc.modelspace().query("HATCH")
    (path,) = hatch.paths
    # okrąg scalony w jeden łuk 360° → dwie połówki, bulge = tan(180°/4) = 1
    assert [round(abs(b), 9) for *_, b in path.vertices] == [1.0, 1.0]
    centers = {(round(x, 6), round(y, 6)) for x, y, _ in path.vertices}
    assert {round(math.dist(c, _xy((300, 300))), 6) for c in centers} == {round(50 * MM, 6)}


def test_cubic_to_arc_roundtrip() -> None:
    for sweep in (90, -90, 45, -30, 5):
        arc = ArcSeg((10, 0), (0, 0), (0, 0), sweep)
        end_angle = math.radians(sweep)
        arc = ArcSeg((10, 0), (10 * math.cos(end_angle), 10 * math.sin(end_angle)), (0, 0), sweep)
        (cubic,) = arc.to_cubics()
        found = cubic_to_arc(cubic, abs_tol=1e-6)
        assert found is not None, sweep
        assert found.center == pytest.approx((0, 0), abs=1e-9)
        assert found.sweep == pytest.approx(sweep)


def test_cubic_to_arc_rejects() -> None:
    assert cubic_to_arc(CubicSeg((50, 400), (100, 350), (150, 450), (200, 400)), 1e-3) is None
    assert cubic_to_arc(CubicSeg((0, 0), (1, 0), (2, 0), (3, 0)), 1e-3) is None  # prosta
    big = ArcSeg((10, 0), (-10, 0), (0, 0), 180)
    (half,) = [c for c in [CubicSeg(big.p1, (10, 13.33), (-10, 13.33), big.p2)]]
    assert cubic_to_arc(half, 1e-3) is None  # półokrąg jedną krzywą — poza zakresem ≤ 90°


def test_merge_arcs_wraps_around_start() -> None:
    q = [ArcSeg((10, 0), (0, 10), (0, 0), 90), ArcSeg((0, 10), (-10, 0), (0, 0), 90),
         LineSeg((-10, 0), (-10, -20)), LineSeg((-10, -20), (10, -20)),
         LineSeg((10, -20), (10, -10)), ArcSeg((10, -10), (10, 0), (5, -5), 90)]
    out = merge_arcs(q, closed=True, tol=1e-6)
    assert sum(isinstance(s, ArcSeg) for s in out) == 2  # ćwiartki (0,0) scalone, (5,-5) osobno
    full = [ArcSeg((10, 0), (0, 10), (0, 0), 90), ArcSeg((0, 10), (-10, 0), (0, 0), 90),
            ArcSeg((-10, 0), (0, -10), (0, 0), 90), ArcSeg((0, -10), (10, 0), (0, 0), 90)]
    (circle,) = merge_arcs(full, closed=True, tol=1e-6)
    assert circle.sweep == pytest.approx(360)


# --- test 12: deduplikacja --------------------------------------------------------------


def test_case12_duplicate_lines(make_pdf: MakePdf) -> None:
    def draw(page: pymupdf.Page) -> None:
        page.draw_line((100, 100), (200, 100))
        page.draw_line((100, 100), (200, 100))
        page.draw_line((200, 100), (100, 100))          # odwrotny kierunek
        page.draw_line((100, 100), (200, 100), color=(1, 0, 0))  # inny styl — zostaje

    report, doc = convert_one(make_pdf(draw))
    assert report.pages[0].entities == {"LINE": 2}
    assert report.pages[0].duplicates_removed == 2


def test_duplicate_rects_and_edge_line(make_pdf: MakePdf) -> None:
    def draw(page: pymupdf.Page) -> None:
        page.draw_rect(pymupdf.Rect(50, 50, 150, 100))
        page.draw_rect(pymupdf.Rect(50, 50, 150, 100))
        page.draw_line((150, 50), (50, 50))  # bok prostokąta

    report, _ = convert_one(make_pdf(draw))
    assert report.pages[0].entities == {"LWPOLYLINE": 1}
    assert report.pages[0].duplicates_removed == 2


def test_dedup_closed_any_start_point() -> None:
    a = [(0, 0), (10, 0), (10, 10), (0, 0)]
    b = [(10, 10), (0, 0), (10, 0), (10, 10)]
    shapes = [Shape([SubPath([LineSeg(p, q) for p, q in zip(pts, pts[1:])], True)], Style())
              for pts in (a, b)]
    out, removed = deduplicate(shapes, grid=1e-3)
    assert removed == 1 and len(out) == 1


def test_duplicate_filled_shapes() -> None:
    sp = SubPath([LineSeg((0, 0), (1, 0)), LineSeg((1, 0), (1, 1)), LineSeg((1, 1), (0, 0))], True)
    fill = Style(stroke_color=None, fill_color=(1, 0, 0))
    shapes = [Shape([sp], fill, stroked=False, filled=True) for _ in range(3)]
    out, removed = deduplicate(shapes, grid=1e-3)
    assert removed == 2 and len(out) == 1


def test_tiny_closing_segment_removed_and_circle_detected() -> None:
    # Jak w eksportach macOS: 4 ćwiartki + mikroskopijny odcinek zamykający (float32).
    quarters = ArcSeg((10, 0), (10, 0), (0, 0), 360).to_cubics()
    end = (10.0, 0.0001)
    segs = [*quarters[:-1], CubicSeg(quarters[-1].p1, quarters[-1].c1, quarters[-1].c2, end),
            LineSeg(end, (10.0, 0.0))]
    page = PageData(index=0, width=100, height=100, space="dxf", unit_scale=1.0,
                    shapes=[Shape([SubPath(segs, closed=True)], Style())])
    out, stats = postprocess_page(page)
    assert stats.zero_length_removed == 1
    (sp,) = out.shapes[0].subpaths
    assert len(sp.segments) == 1 and isinstance(sp.segments[0], ArcSeg)
    assert abs(sp.segments[0].sweep) == pytest.approx(360, abs=0.01)


def test_quarters_summing_slightly_over_360_merge() -> None:
    q = [ArcSeg((10, 0), (0, 10), (0, 0), 90.000004), ArcSeg((0, 10), (-10, 0), (0, 0), 90.000004),
         ArcSeg((-10, 0), (0, -10), (0, 0), 90.000004), ArcSeg((0, -10), (10, 0), (0, 0), 90.000004)]
    (full,) = merge_arcs(q, closed=True, tol=1e-6)
    assert full.sweep == pytest.approx(360, abs=1e-4)


def test_zero_length_and_rounding() -> None:
    shape = Shape([SubPath([LineSeg((1, 1), (1, 1))]),
                   SubPath([LineSeg((0.1 + 0.2, 0), (1.0000000004, 0))])], Style())
    shape = round_shape(shape)
    assert shape.subpaths[1].segments[0] == LineSeg((0.3, 0), (1.0, 0))
    out, removed = remove_zero_length([shape])
    assert removed == 1 and len(out[0].subpaths) == 1


# --- --join ------------------------------------------------------------------------------


def test_join_lines_into_polylines(make_pdf: MakePdf) -> None:
    def draw(page: pymupdf.Page) -> None:
        for a, b in [((10, 10), (100, 10)), ((100, 10), (100, 100)), ((10, 100), (100, 100)),
                     ((10, 100), (10, 10)),                       # zamknięty kwadrat
                     ((200, 10), (300, 10)), ((300, 10), (300, 80))]:  # otwarta łamana
            page.draw_line(a, b)
        page.draw_line((300, 80), (400, 80), color=(1, 0, 0))     # inny styl — osobno

    pdf = make_pdf(draw)
    assert convert_one(pdf)[0].pages[0].entities == {"LINE": 7}
    report, doc = convert_one(pdf, join=True)
    assert report.pages[0].entities == {"LWPOLYLINE": 2, "LINE": 1}
    assert report.pages[0].joined == 6
    closed = [e for e in doc.modelspace().query("LWPOLYLINE") if e.closed]
    assert len(closed) == 1 and len(closed[0]) == 4


def test_join_stops_at_branches() -> None:
    # T: trzy odcinki spotykają się w (10, 0) — nie łączymy przez rozgałęzienie
    lines = [((0, 0), (10, 0)), ((10, 0), (20, 0)), ((10, 0), (10, 10)), ((20, 0), (30, 0))]
    shapes = [Shape([SubPath([LineSeg(a, b)])], Style()) for a, b in lines]
    out, joined = join_subpaths(shapes, grid=1e-3)
    lengths = sorted(len(sp.segments) for s in out for sp in s.subpaths)
    assert lengths == [1, 1, 2] and joined == 2


def test_join_with_arcs_gives_bulge_polyline(make_pdf: MakePdf) -> None:
    def draw(page: pymupdf.Page) -> None:
        page.draw_line((100, 300), (250, 300))
        sh = page.new_shape()
        sh.draw_sector((250, 350), (250, 300), -90, fullSector=False)
        sh.finish(color=(0, 0, 0), closePath=False)
        sh.commit()

    report, doc = convert_one(make_pdf(draw), join=True)
    assert report.pages[0].entities == {"LWPOLYLINE": 1}
    (pl,) = doc.modelspace().query("LWPOLYLINE")
    assert len(pl) == 3 and any(abs(b) > 0.4 for *_, b in pl.get_points("xyb"))


def test_postprocess_requires_dxf_space() -> None:
    with pytest.raises(ValueError):
        postprocess_page(PageData(index=0, width=1, height=1), PostprocessOptions())
