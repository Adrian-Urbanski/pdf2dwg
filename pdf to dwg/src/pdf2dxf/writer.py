"""Zapis DXF przez ezdxf.

Writer dostaje strony już w przestrzeni DXF (po :mod:`pdf2dxf.transform`
i :mod:`pdf2dxf.postprocess`) i nie importuje PyMuPDF.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf import zoom
from ezdxf.colors import DXF_DEFAULT_COLORS, float2transparency, int2rgb, rgb2int
from ezdxf.document import Drawing
from ezdxf.layouts import Modelspace
from ezdxf.lldxf.const import VALID_DXF_LINEWEIGHTS
from ezdxf.math import BSpline
from ezdxf.path import Path as EzPath
from ezdxf.path import to_bsplines_and_vertices

from pdf2dxf.model import (
    RGB,
    ArcSeg,
    CubicSeg,
    DashPattern,
    LineSeg,
    PageData,
    Point,
    Shape,
    Style,
    SubPath,
    TextItem,
)
from pdf2dxf.transform import INSUNITS, UNIT_FACTORS

log = logging.getLogger(__name__)

DEFAULT_LAYER = "PDF"
TEXT_STYLE = "PDF_TEXT"
TEXT_FONT = "arial.ttf"
ACI_BLACK_WHITE = 7
BLACK_THRESHOLD = 0.05
"""Kolor o wszystkich składowych ≤ tej wartości traktujemy jako czarny (ACI 7)."""
BACKGROUND_COVERAGE = 0.9
"""Białe wypełnienie zakrywające co najmniej taki ułamek strony to tło."""
MM_PER_PT = UNIT_FACTORS["mm"]
FULL_CIRCLE_TOL = 0.5
"""Łuk o kącie 360° ± tyle stopni zapisywany jest jako CIRCLE."""
_INVALID_LAYER_CHARS = set('<>/\\":;?*|=`')
_HATCH_STYLE_NORMAL = 0  # wyspy na przemian = reguła parzystości (even-odd)
_BOUNDARY_EXTERNAL = 1
_BOUNDARY_DEFAULT = 0


@dataclass
class WriterOptions:
    """Opcje zapisu DXF (podzbiór opcji CLI)."""

    units: str = "mm"
    dxf_version: str = "R2010"
    curves: str = "spline"
    flatten_tol_mm: float = 0.01
    layers: str = "by-color"
    fills: str = "hatch"
    text_height_factor: float = 0.7


# ---------------------------------------------------------------------------
# kolory, grubości, nazwy
# ---------------------------------------------------------------------------


def rgb255(color: RGB) -> tuple[int, int, int]:
    """Kolor 0–1 → 0–255."""
    r, g, b = (max(0, min(255, round(c * 255))) for c in color)
    return (r, g, b)


def is_black(color: RGB) -> bool:
    return all(c <= BLACK_THRESHOLD for c in color)


@lru_cache(maxsize=4096)
def nearest_aci(rgb: tuple[int, int, int]) -> int:
    """Najbliższy kolor ACI (1–255) w sensie odległości euklidesowej RGB."""
    best, best_d = ACI_BLACK_WHITE, math.inf
    for aci in range(1, 256):
        cr, cg, cb = int2rgb(DXF_DEFAULT_COLORS[aci])
        d = (cr - rgb[0]) ** 2 + (cg - rgb[1]) ** 2 + (cb - rgb[2]) ** 2
        if d < best_d:
            best, best_d = aci, d
    return best


def color_attribs(color: RGB | None) -> dict[str, int]:
    """Atrybuty koloru encji: ACI + kolor prawdziwy.

    Czarny dostaje tylko ACI 7 (bez koloru prawdziwego, który ma pierwszeństwo
    i dałby czarne linie na czarnym tle CAD).
    """
    if color is None or is_black(color):
        return {"color": ACI_BLACK_WHITE}
    rgb = rgb255(color)
    return {"color": nearest_aci(rgb), "true_color": rgb2int(rgb)}


def lineweight(width_pt: float) -> int:
    """Grubość linii w pt → najbliższa dopuszczalna wartość lineweight DXF (setne mm)."""
    target = max(0.0, width_pt) * MM_PER_PT * 100.0
    return min(VALID_DXF_LINEWEIGHTS, key=lambda v: (abs(v - target), v))


def sanitize_layer_name(name: str) -> str:
    """Usuwa znaki niedozwolone w nazwach warstw DXF."""
    cleaned = "".join(
        "_" if (ch in _INVALID_LAYER_CHARS or ord(ch) < 32) else ch for ch in name
    ).strip()
    return cleaned[:255] or DEFAULT_LAYER


def color_layer_name(color: RGB | None) -> str:
    r, g, b = rgb255(color) if color is not None else (0, 0, 0)
    return f"PDF_{r:02X}{g:02X}{b:02X}"


# ---------------------------------------------------------------------------
# geometria pomocnicza
# ---------------------------------------------------------------------------


def to_ezdxf_path(sp: SubPath, *, close: bool | None = None) -> EzPath:
    """Podścieżka modelu → :class:`ezdxf.path.Path`."""
    path = EzPath(sp.start)
    for seg in sp.segments:
        if isinstance(seg, LineSeg):
            path.line_to(seg.p2)
        else:  # CubicSeg albo ArcSeg (po postprocessingu) jako krzywe Béziera
            for cubic in [seg] if isinstance(seg, CubicSeg) else seg.to_cubics():
                path.curve4_to(cubic.p2, cubic.c1, cubic.c2)
    if sp.closed if close is None else close:
        path.close()
    return path


def bulge_points(sp: SubPath) -> list[tuple[float, float, float]]:
    """Wierzchołki LWPOLYLINE ``(x, y, bulge)`` dla podścieżki z odcinków i łuków.

    Bulge wierzchołka dotyczy segmentu, który się w nim zaczyna. Łuki powyżej
    180° są dzielone na połowy (bulge pełnego okręgu byłby nieskończony).
    """
    segs: list[LineSeg | ArcSeg] = []
    for s in sp.segments:
        if isinstance(s, ArcSeg) and abs(s.sweep) > 180.0:
            segs.extend(s.split())
        else:
            assert isinstance(s, (LineSeg, ArcSeg))
            segs.append(s)
    pts = [(s.start[0], s.start[1], s.bulge if isinstance(s, ArcSeg) else 0.0) for s in segs]
    if not sp.closed:
        pts.append((segs[-1].end[0], segs[-1].end[1], 0.0))
    return pts


def start_at_curve(sp: SubPath) -> SubPath:
    """Dla zamkniętej podścieżki z liniami i krzywymi przesuwa punkt startu na
    początek krzywej, żeby linie przed i za punktem startu tworzyły jedną polilinię."""
    segs = sp.segments
    if not sp.closed or not isinstance(segs[0], LineSeg) or not isinstance(segs[-1], LineSeg):
        return sp
    for i in range(1, len(segs)):
        if not isinstance(segs[i], LineSeg):
            return SubPath(segs[i:] + segs[:i], closed=True)
    return sp


def flatten(sp: SubPath, tol: float, *, close: bool | None = None) -> list[Point]:
    """Spłaszcza podścieżkę do łamanej z tolerancją ``tol`` (jednostki DXF)."""
    pts = [(v.x, v.y) for v in to_ezdxf_path(sp, close=close).flattening(distance=tol)]
    dedup: list[Point] = []
    for p in pts:
        if not dedup or p != dedup[-1]:
            dedup.append(p)
    return dedup


def signed_area(poly: Sequence[Point]) -> float:
    """Pole ze znakiem (dodatnie = przeciwnie do wskazówek zegara przy osi Y w górę)."""
    n = len(poly)
    return 0.5 * sum(
        poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n)
    )


def point_in_polygon(pt: Point, poly: Sequence[Point]) -> bool:
    """Test parzystości przecięć promienia."""
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xc = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xc > x:
                inside = not inside
    return inside


def hatch_boundaries(
    polys: list[list[Point]], even_odd: bool
) -> list[tuple[list[Point], bool]]:
    """Wybiera kontury do HATCH rysowanego regułą parzystości.

    Dla reguły nonzero zostawia tylko te kontury, na których zmienia się stan
    wypełnienia (np. wewnętrzny kontur o tym samym kierunku obiegu co
    zewnętrzny nie tworzy dziury). Zwraca (kontur, czy_zewnętrzny).
    """
    probes = [_probe(p) for p in polys]
    containers = [
        [j for j, other in enumerate(polys) if j != i and point_in_polygon(probes[i], other)]
        for i in range(len(polys))
    ]
    keep = list(range(len(polys)))
    if not even_odd:
        signs = [1 if signed_area(p) >= 0 else -1 for p in polys]
        keep = []
        for i in range(len(polys)):
            outside = sum(signs[j] for j in containers[i])
            if (outside != 0) != (outside + signs[i] != 0):
                keep.append(i)
    kept = set(keep)
    return [(polys[i], not any(j in kept for j in containers[i])) for i in keep]


def _probe(poly: Sequence[Point]) -> Point:
    """Punkt kontrolny konturu do testu zawierania (środek pierwszej krawędzi)."""
    (x1, y1), (x2, y2) = poly[0], poly[1]
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _bbox(shape: Shape) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for sp in shape.subpaths:
        for x, y in sp.points():
            xs.append(x)
            ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------------------
# writer
# ---------------------------------------------------------------------------


class DxfWriter:
    """Buduje jeden dokument DXF z jednej lub wielu stron."""

    def __init__(self, options: WriterOptions | None = None) -> None:
        self.options = options or WriterOptions()
        self.doc: Drawing = ezdxf.new(self.options.dxf_version, setup=False)
        self.msp: Modelspace = self.doc.modelspace()
        self._linetypes: dict[tuple[float, ...], str] = {}
        self._setup_header()

    # -- nagłówek -------------------------------------------------------------

    def _setup_header(self) -> None:
        units = self.options.units
        self.doc.header["$INSUNITS"] = INSUNITS[units]
        self.doc.header["$MEASUREMENT"] = 0 if units == "in" else 1
        self.doc.header["$LWDISPLAY"] = 1

    # -- zasoby: warstwy, typy linii --------------------------------------------

    def layer_for(self, color: RGB | None, ocg: str | None) -> str:
        """Nazwa warstwy dla elementu (tworzy warstwę przy pierwszym użyciu)."""
        mode = self.options.layers
        layer_color: RGB | None = None
        if mode == "single":
            name = DEFAULT_LAYER
        elif mode == "by-ocg" and ocg:
            name = sanitize_layer_name(ocg)
        else:  # by-color albo by-ocg bez warstwy OCG
            name, layer_color = color_layer_name(color), color
        if name not in self.doc.layers:
            a = color_attribs(layer_color)
            self.doc.layers.add(name, color=a["color"], true_color=a.get("true_color"))
        return name

    def linetype_for(self, dashes: DashPattern, k: float) -> str:
        """Własny typ linii z wzoru PDF przeliczonego na jednostki DXF (z cache)."""
        lengths = tuple(round(v * k, 9) for v in dashes.lengths)
        name = self._linetypes.get(lengths)
        if name is None:
            name = f"PDF_DASH_{len(self._linetypes) + 1}"
            pattern: list[float] = [sum(lengths)]
            for i, v in enumerate(lengths):
                pattern.append(v if i % 2 == 0 else -v)
            desc = "PDF [" + " ".join(f"{v:g}" for v in dashes.lengths) + "] pt"
            self.doc.linetypes.add(name, pattern=pattern, description=desc)
            self._linetypes[lengths] = name
        return name

    def stroke_attribs(self, style: Style, k: float) -> dict[str, Any]:
        color = style.stroke_color
        attribs: dict[str, Any] = {
            "layer": self.layer_for(color, style.layer),
            "lineweight": lineweight(style.line_width),
            **color_attribs(color),
        }
        if style.dashes is not None and sum(style.dashes.lengths) * k > 0:
            attribs["linetype"] = self.linetype_for(style.dashes, k)
        if style.stroke_opacity < 1.0:
            attribs["transparency"] = _transparency(style.stroke_opacity)
        return attribs

    def fill_attribs(self, style: Style) -> dict[str, Any]:
        color = style.fill_color
        attribs: dict[str, Any] = {
            "layer": self.layer_for(color, style.layer),
            **color_attribs(color),
        }
        if style.fill_opacity < 1.0:
            attribs["transparency"] = _transparency(style.fill_opacity)
        return attribs

    # -- strony ---------------------------------------------------------------

    def add_page(self, page: PageData) -> Counter[str]:
        """Dodaje stronę (w przestrzeni DXF). Zwraca liczbę encji wg typu."""
        if page.space != "dxf":
            raise ValueError("writer oczekuje strony w przestrzeni DXF")
        counts: Counter[str] = Counter()
        tol = self.options.flatten_tol_mm / MM_PER_PT * page.unit_scale
        for shape in page.shapes:
            counts.update(self._add_shape(shape, page, tol))
        for item in page.texts:
            if self._add_text(item):
                counts["TEXT"] += 1
        return counts

    # -- tekst ------------------------------------------------------------------

    def text_style(self) -> str:
        """Styl tekstu z fontem TTF obsługującym polskie znaki (tworzony raz)."""
        if TEXT_STYLE not in self.doc.styles:
            self.doc.styles.add(TEXT_STYLE, font=TEXT_FONT)
        return TEXT_STYLE

    def _add_text(self, item: TextItem) -> bool:
        height = item.size * self.options.text_height_factor
        if not item.text.strip() or height <= 0:
            return False
        attribs: dict[str, Any] = {
            "layer": self.layer_for(item.color, item.layer),
            "style": self.text_style(),
            "insert": item.origin,
            "height": height,
            "rotation": normalize_angle(item.angle),
            **color_attribs(item.color),
        }
        if item.opacity < 1.0:
            attribs["transparency"] = _transparency(item.opacity)
        self.msp.add_text(item.text, dxfattribs=attribs)
        return True

    def _add_shape(self, shape: Shape, page: PageData, tol: float) -> Counter[str]:
        counts: Counter[str] = Counter()
        if not shape.subpaths:
            return counts
        if shape.filled and _is_background(shape, page):
            log.debug("pominięto białe tło strony %d", page.number)
            return counts
        fills = self.options.fills
        if shape.filled and fills == "hatch":
            if self._add_hatch(shape, tol):
                counts["HATCH"] += 1
        elif shape.filled and fills == "outline" and not shape.stroked:
            attribs = self.fill_attribs(shape.style)
            for sp in shape.subpaths:
                closed = SubPath(sp.segments, closed=True)
                counts.update(self._add_curve(closed, attribs, tol))
        if shape.stroked:
            attribs = self.stroke_attribs(shape.style, page.unit_scale)
            for sp in shape.subpaths:
                counts.update(self._add_curve(sp, attribs, tol))
        return counts

    def _add_curve(self, sp: SubPath, attribs: dict[str, Any], tol: float) -> list[str]:
        """Rysuje podścieżkę jako LINE/LWPOLYLINE/ARC/CIRCLE/SPLINE.

        Zwraca typy utworzonych encji.
        """
        segs = sp.segments
        if not segs:
            return []
        if all(isinstance(s, LineSeg) for s in segs):
            return [self._add_lines(sp.points(), sp.closed, attribs)]
        if all(isinstance(s, (LineSeg, ArcSeg)) for s in segs):
            if len(segs) == 1 and isinstance(segs[0], ArcSeg):
                arc = segs[0]
                if abs(abs(arc.sweep) - 360.0) < FULL_CIRCLE_TOL:
                    self.msp.add_circle(arc.center, arc.radius, dxfattribs=attribs)
                    return ["CIRCLE"]
                if not sp.closed:
                    self._add_arc(arc, attribs)
                    return ["ARC"]
            self.msp.add_lwpolyline(bulge_points(sp), format="xyb", close=sp.closed,
                                    dxfattribs=attribs)
            return ["LWPOLYLINE"]
        if self.options.curves == "polyline":
            pts = flatten(sp, tol)
            closed = sp.closed
            if closed and len(pts) > 2 and pts[0] == pts[-1]:
                pts.pop()
            return [self._add_lines(pts, closed, attribs)]
        kinds: list[str] = []
        for part in to_bsplines_and_vertices(to_ezdxf_path(start_at_curve(sp))):
            if isinstance(part, BSpline):
                spline = self.msp.add_spline(dxfattribs=attribs)
                spline.apply_construction_tool(part)
                kinds.append("SPLINE")
            else:
                kinds.append(self._add_lines([(v.x, v.y) for v in part], False, attribs))
        return kinds

    def _add_arc(self, arc: ArcSeg, attribs: dict[str, Any]) -> None:
        """ARC w DXF biegnie zawsze przeciwnie do wskazówek zegara od kąta początkowego."""
        a1 = arc.start_angle
        a2 = math.degrees(math.atan2(arc.p2[1] - arc.center[1], arc.p2[0] - arc.center[0]))
        start, end = (a1, a2) if arc.sweep > 0 else (a2, a1)
        self.msp.add_arc(arc.center, arc.radius, normalize_angle(start), normalize_angle(end),
                         dxfattribs=attribs)

    def _add_lines(self, pts: list[Point], closed: bool, attribs: dict[str, Any]) -> str:
        if closed and len(pts) > 2 and _same(pts[0], pts[-1]):
            pts = pts[:-1]
        if len(pts) == 2 and not closed:
            self.msp.add_line(pts[0], pts[1], dxfattribs=attribs)
            return "LINE"
        self.msp.add_lwpolyline(pts, format="xy", close=closed, dxfattribs=attribs)
        return "LWPOLYLINE"

    def _add_hatch(self, shape: Shape, tol: float) -> bool:
        polys: list[list[Point]] = []
        exact: dict[int, list[tuple[float, float, float]]] = {}
        for sp in shape.subpaths:
            pts = flatten(sp, tol, close=True)
            if len(pts) > 2 and _same(pts[0], pts[-1]):
                pts.pop()
            if len(pts) >= 3 and abs(signed_area(pts)) > tol * tol:
                if all(isinstance(s, (LineSeg, ArcSeg)) for s in sp.segments):
                    # kontur z odcinków i łuków — dokładnie, z wypukłościami (bulge)
                    exact[id(pts)] = bulge_points(SubPath(sp.segments, closed=True))
                polys.append(pts)
        if not polys:
            return False
        attribs = self.fill_attribs(shape.style)
        hatch = self.msp.add_hatch(color=attribs["color"], dxfattribs=attribs)
        true_color = attribs.get("true_color")
        hatch.set_solid_fill(
            color=attribs["color"],
            style=_HATCH_STYLE_NORMAL,
            rgb=int2rgb(true_color) if true_color is not None else None,
        )
        for poly, external in hatch_boundaries(polys, shape.even_odd):
            vertices = exact.get(id(poly)) or [(x, y, 0.0) for x, y in poly]
            hatch.paths.add_polyline_path(
                vertices, is_closed=True,
                flags=_BOUNDARY_EXTERNAL if external else _BOUNDARY_DEFAULT,
            )
        return True

    # -- zapis ----------------------------------------------------------------

    def save(self, path: Path) -> None:
        """Ustawia widok na całość rysunku i zapisuje plik."""
        try:
            zoom.extents(self.msp)
        except Exception as exc:  # pusty rysunek itp. — widok nie jest krytyczny
            log.debug("zoom.extents nie powiódł się: %s", exc)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.doc.saveas(path)


def _is_background(shape: Shape, page: PageData) -> bool:
    color = shape.style.fill_color
    if color is None or any(c < 0.98 for c in color):
        return False
    if shape.stroked and shape.style.stroke_color is not None and not all(
        c >= 0.98 for c in shape.style.stroke_color
    ):
        return False
    x0, y0, x1, y1 = _bbox(shape)
    page_area = page.width * page.height
    return page_area > 0 and (x1 - x0) * (y1 - y0) >= BACKGROUND_COVERAGE * page_area


def normalize_angle(angle: float) -> float:
    """Kąt w stopniach sprowadzony do [0, 360), z wyzerowaniem szumu numerycznego."""
    a = round(angle % 360.0, 9)
    return 0.0 if a >= 360.0 else a


def _transparency(opacity: float) -> int:
    """Krycie 0–1 → surowa wartość atrybutu DXF ``transparency``."""
    return float2transparency(max(0.0, min(1.0, 1.0 - opacity)))


def _same(a: Point, b: Point, tol: float = 1e-9) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol
