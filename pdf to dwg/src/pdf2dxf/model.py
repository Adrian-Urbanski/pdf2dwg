"""Model pośredni łączący backend ekstrakcji z writerem DXF.

Backend tworzy :class:`PageData` w jednostkach PDF (punkty, początek w lewym
górnym rogu CropBox, oś Y w dół, strona *nieobrócona*). Moduł
:mod:`pdf2dxf.transform` zamienia ją na :class:`PageData` w przestrzeni DXF
(jednostki rysunku, oś Y w górę, obrót strony zastosowany) — od tego miejsca
geometria jest gotowa do zapisu. Pole :attr:`PageData.space` mówi, w której
przestrzeni są współrzędne.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

Point: TypeAlias = tuple[float, float]
RGB: TypeAlias = tuple[float, float, float]
"""Kolor RGB, składowe 0–1."""


@dataclass(frozen=True)
class DashPattern:
    """Wzór linii przerywanej z PDF: długości (kreska, przerwa, …) i przesunięcie, w pt."""

    lengths: tuple[float, ...]
    phase: float = 0.0


@dataclass(frozen=True)
class Style:
    """Styl rysowania ścieżki. Długości (grubość, wzór kresek) zawsze w pt."""

    stroke_color: RGB | None = (0.0, 0.0, 0.0)
    fill_color: RGB | None = None
    line_width: float = 1.0
    dashes: DashPattern | None = None
    layer: str | None = None
    stroke_opacity: float = 1.0
    fill_opacity: float = 1.0


@dataclass(frozen=True)
class LineSeg:
    """Odcinek prostej."""

    p1: Point
    p2: Point

    @property
    def start(self) -> Point:
        return self.p1

    @property
    def end(self) -> Point:
        return self.p2

    def reversed(self) -> LineSeg:
        return LineSeg(self.p2, self.p1)


@dataclass(frozen=True)
class CubicSeg:
    """Krzywa Béziera 3. stopnia: punkt początkowy, dwa kontrolne, końcowy."""

    p1: Point
    c1: Point
    c2: Point
    p2: Point

    @property
    def start(self) -> Point:
        return self.p1

    @property
    def end(self) -> Point:
        return self.p2

    def reversed(self) -> CubicSeg:
        return CubicSeg(self.p2, self.c2, self.c1, self.p1)


@dataclass(frozen=True)
class ArcSeg:
    """Łuk okręgu (wynik postprocessingu, tylko w przestrzeni DXF).

    ``sweep`` to kąt w stopniach od ``p1`` do ``p2`` wokół ``center``:
    dodatni = przeciwnie do ruchu wskazówek zegara (oś Y w górę).
    """

    p1: Point
    p2: Point
    center: Point
    sweep: float

    @property
    def start(self) -> Point:
        return self.p1

    @property
    def end(self) -> Point:
        return self.p2

    @property
    def radius(self) -> float:
        return math.dist(self.center, self.p1)

    def reversed(self) -> ArcSeg:
        return ArcSeg(self.p2, self.p1, self.center, -self.sweep)

    @property
    def bulge(self) -> float:
        """Wypukłość (bulge) segmentu LWPOLYLINE: ``tan(sweep / 4)``."""
        return math.tan(math.radians(self.sweep) / 4.0)

    @property
    def start_angle(self) -> float:
        """Kąt (°) punktu ``p1`` względem środka."""
        return math.degrees(math.atan2(self.p1[1] - self.center[1], self.p1[0] - self.center[0]))

    def split(self) -> tuple[ArcSeg, ArcSeg]:
        """Dzieli łuk na dwie równe połowy."""
        mid_angle = math.radians(self.start_angle + self.sweep / 2.0)
        r = self.radius
        mid = (self.center[0] + r * math.cos(mid_angle), self.center[1] + r * math.sin(mid_angle))
        half = self.sweep / 2.0
        return ArcSeg(self.p1, mid, self.center, half), ArcSeg(mid, self.p2, self.center, half)

    def to_cubics(self) -> list[CubicSeg]:
        """Przybliżenie łuku krzywymi Béziera (po jednej na każde ≤ 90°)."""
        cx, cy = self.center
        r = self.radius
        a0 = math.atan2(self.p1[1] - cy, self.p1[0] - cx)
        sweep = math.radians(self.sweep)
        n = max(1, math.ceil(abs(sweep) / (math.pi / 2) - 1e-9))
        step = sweep / n
        kappa = 4.0 / 3.0 * math.tan(step / 4.0)
        result: list[CubicSeg] = []
        start = self.p1
        for i in range(n):
            t0, t1 = a0 + i * step, a0 + (i + 1) * step
            end = self.p2 if i == n - 1 else (cx + r * math.cos(t1), cy + r * math.sin(t1))
            c1 = (cx + r * (math.cos(t0) - kappa * math.sin(t0)),
                  cy + r * (math.sin(t0) + kappa * math.cos(t0)))
            c2 = (cx + r * (math.cos(t1) + kappa * math.sin(t1)),
                  cy + r * (math.sin(t1) - kappa * math.cos(t1)))
            result.append(CubicSeg(start, c1, c2, end))
            start = end
        return result


Segment: TypeAlias = LineSeg | CubicSeg | ArcSeg


@dataclass
class SubPath:
    """Ciągła podścieżka. ``closed`` oznacza, że koniec łączy się z początkiem."""

    segments: list[Segment]
    closed: bool = False

    @property
    def start(self) -> Point:
        return self.segments[0].start

    @property
    def end(self) -> Point:
        return self.segments[-1].end

    def points(self) -> list[Point]:
        """Kolejne punkty węzłowe (bez punktów kontrolnych)."""
        if not self.segments:
            return []
        return [self.segments[0].start, *(s.end for s in self.segments)]


@dataclass
class Shape:
    """Jedna ścieżka PDF: kilka podścieżek o wspólnym stylu."""

    subpaths: list[SubPath]
    style: Style
    stroked: bool = True
    filled: bool = False
    even_odd: bool = False


@dataclass
class TextItem:
    """Fragment tekstu (span).

    W przestrzeni PDF: ``size`` to rozmiar fontu w pt, ``angle`` to kąt kierunku
    tekstu w stopniach w układzie z osią Y w dół (``atan2(dir.y, dir.x)``).
    W przestrzeni DXF: ``size`` to rozmiar fontu w jednostkach rysunku,
    ``angle`` to kąt obrotu encji TEXT (przeciwnie do wskazówek zegara).
    """

    text: str
    origin: Point
    size: float
    angle: float = 0.0
    font: str = ""
    color: RGB = (0.0, 0.0, 0.0)
    layer: str | None = None
    opacity: float = 1.0
    width: float = 0.0
    """Długość tekstu wzdłuż linii bazowej (w jednostkach przestrzeni), 0 = nieznana."""


@dataclass
class PageData:
    """Dane jednej strony.

    ``width``/``height`` to wymiary strony w jednostkach przestrzeni
    (w przestrzeni PDF — strony nieobróconej). ``unit_scale`` to współczynnik
    ``k`` (jednostki DXF na 1 pt), ustawiany przez transformację.
    """

    index: int
    width: float
    height: float
    rotation: int = 0
    shapes: list[Shape] = field(default_factory=list)
    texts: list[TextItem] = field(default_factory=list)
    image_count: int = 0
    image_coverage: float = 0.0
    warnings: list[str] = field(default_factory=list)
    space: Literal["pdf", "dxf"] = "pdf"
    unit_scale: float = 1.0

    @property
    def number(self) -> int:
        """Numer strony liczony od 1."""
        return self.index + 1
