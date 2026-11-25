"""Transformacja przestrzeni PDF → przestrzeń DXF.

To jedyne miejsce, w którym zmienia się układ współrzędnych:

1. obrót strony (``/Rotate``) — tak jak ``page.rotation_matrix`` w PyMuPDF,
   bo backend zwraca współrzędne strony nieobróconej;
2. odbicie osi Y (PDF: Y w dół, DXF: Y w górę);
3. jednostki i skala: ``k = współczynnik_jednostki × skala``;
4. przesunięcie (układanie stron obok siebie w trybie ``--single-file``).

Grubość linii i wzory kresek (w :class:`~pdf2dxf.model.Style`) zostają w pt —
writer przelicza je sam (grubość nie podlega skali, kreski tak jak geometria,
przez ``PageData.unit_scale``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from pdf2dxf.model import (
    ArcSeg,
    CubicSeg,
    LineSeg,
    PageData,
    Point,
    Segment,
    Shape,
    SubPath,
    TextItem,
)

UNIT_FACTORS: dict[str, float] = {
    "mm": 25.4 / 72.0,
    "cm": 2.54 / 72.0,
    "m": 0.0254 / 72.0,
    "in": 1.0 / 72.0,
    "pt": 1.0,
}
"""Ile jednostek DXF przypada na 1 pt (1/72 cala)."""

INSUNITS: dict[str, int] = {"mm": 4, "cm": 5, "m": 6, "in": 1, "pt": 0}
"""Wartości zmiennej nagłówka ``$INSUNITS`` (pt → 0 = bez jednostek)."""


@dataclass(frozen=True)
class Affine:
    """Przekształcenie afiniczne w konwencji PyMuPDF.

    ``x' = a·x + c·y + e``, ``y' = b·x + d·y + f``.
    """

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    def apply(self, p: Point) -> Point:
        x, y = p
        return (self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f)

    def apply_vector(self, v: Point) -> Point:
        x, y = v
        return (self.a * x + self.c * y, self.b * x + self.d * y)

    def then(self, other: Affine) -> Affine:
        """Złożenie: najpierw ``self``, potem ``other``."""
        return Affine(
            a=self.a * other.a + self.b * other.c,
            b=self.a * other.b + self.b * other.d,
            c=self.c * other.a + self.d * other.c,
            d=self.c * other.b + self.d * other.d,
            e=self.e * other.a + self.f * other.c + other.e,
            f=self.e * other.b + self.f * other.d + other.f,
        )

    @property
    def determinant(self) -> float:
        return self.a * self.d - self.b * self.c


def normalize_rotation(rotation: int) -> int:
    """Sprowadza kąt obrotu strony do 0, 90, 180 lub 270."""
    r = int(rotation) % 360
    if r % 90:
        raise ValueError(f"obrót strony musi być wielokrotnością 90°: {rotation}")
    return r


def rotation_matrix(width: float, height: float, rotation: int) -> Affine:
    """Macierz obrotu strony nieobróconej ``width × height`` (jak ``page.rotation_matrix``)."""
    r = normalize_rotation(rotation)
    if r == 90:
        return Affine(0, 1, -1, 0, height, 0)
    if r == 180:
        return Affine(-1, 0, 0, -1, width, height)
    if r == 270:
        return Affine(0, -1, 1, 0, 0, width)
    return Affine()


def rotated_size(width: float, height: float, rotation: int) -> tuple[float, float]:
    """Wymiary strony po obrocie (tak, jak ją widać w przeglądarce PDF)."""
    if normalize_rotation(rotation) in (90, 270):
        return height, width
    return width, height


@dataclass(frozen=True)
class Transform:
    """Przekształcenie punktów strony PDF (pt) do jednostek DXF."""

    matrix: Affine
    k: float
    width: float
    """Szerokość strony po obrocie, w jednostkach DXF."""
    height: float
    """Wysokość strony po obrocie, w jednostkach DXF."""

    def point(self, p: Point) -> Point:
        return self.matrix.apply(p)

    def vector(self, v: Point) -> Point:
        return self.matrix.apply_vector(v)

    def length(self, value: float) -> float:
        return value * self.k

    def angle(self, pdf_degrees: float) -> float:
        """Kąt kierunku z układu PDF (Y w dół) na kąt DXF (przeciwnie do wskazówek zegara)."""
        t = math.radians(pdf_degrees)
        vx, vy = self.vector((math.cos(t), math.sin(t)))
        return math.degrees(math.atan2(vy, vx))

    @property
    def mirrors(self) -> bool:
        """Czy przekształcenie zmienia orientację (odbicie osi Y — zawsze tak)."""
        return self.matrix.determinant < 0


def make_transform(
    width: float,
    height: float,
    rotation: int = 0,
    units: str = "mm",
    scale: float = 1.0,
    offset: Point = (0.0, 0.0),
) -> Transform:
    """Buduje transformację dla strony nieobróconej ``width × height`` pt.

    Wzór (po obrocie strony): ``x_dxf = x·k + ox``, ``y_dxf = (H − y)·k + oy``.
    """
    if units not in UNIT_FACTORS:
        raise ValueError(f"nieznane jednostki: {units}")
    if scale <= 0:
        raise ValueError(f"skala musi być dodatnia: {scale}")
    k = UNIT_FACTORS[units] * scale
    rot = rotation_matrix(width, height, rotation)
    w, h = rotated_size(width, height, rotation)
    flip = Affine(k, 0, 0, -k, offset[0], h * k + offset[1])
    return Transform(matrix=rot.then(flip), k=k, width=w * k, height=h * k)


def page_transform(
    page: PageData, units: str = "mm", scale: float = 1.0, offset: Point = (0.0, 0.0)
) -> Transform:
    """Transformacja dla strony z modelu (w przestrzeni PDF)."""
    return make_transform(page.width, page.height, page.rotation, units, scale, offset)


def transform_page(page: PageData, tr: Transform) -> PageData:
    """Zwraca kopię strony z geometrią i tekstem w przestrzeni DXF."""
    if page.space != "pdf":
        raise ValueError("strona jest już w przestrzeni DXF")
    return replace(
        page,
        width=tr.width,
        height=tr.height,
        rotation=0,
        shapes=[_transform_shape(s, tr) for s in page.shapes],
        texts=[_transform_text(t, tr) for t in page.texts],
        warnings=list(page.warnings),
        space="dxf",
        unit_scale=tr.k,
    )


def _transform_shape(shape: Shape, tr: Transform) -> Shape:
    return replace(
        shape,
        subpaths=[
            SubPath([transform_segment(s, tr) for s in sp.segments], sp.closed)
            for sp in shape.subpaths
        ],
    )


def transform_segment(seg: Segment, tr: Transform) -> Segment:
    """Przekształca pojedynczy segment."""
    if isinstance(seg, LineSeg):
        return LineSeg(tr.point(seg.p1), tr.point(seg.p2))
    if isinstance(seg, CubicSeg):
        return CubicSeg(tr.point(seg.p1), tr.point(seg.c1), tr.point(seg.c2), tr.point(seg.p2))
    sweep = -seg.sweep if tr.mirrors else seg.sweep
    return ArcSeg(tr.point(seg.p1), tr.point(seg.p2), tr.point(seg.center), sweep)


def _transform_text(item: TextItem, tr: Transform) -> TextItem:
    return replace(
        item,
        origin=tr.point(item.origin),
        size=tr.length(item.size),
        angle=tr.angle(item.angle),
        width=tr.length(item.width),
    )
