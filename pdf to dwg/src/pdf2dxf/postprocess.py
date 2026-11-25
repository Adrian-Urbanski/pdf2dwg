"""Postprocessing w przestrzeni DXF.

Kolejność: zaokrąglenie współrzędnych → usunięcie odcinków zerowej długości →
deduplikacja → wykrywanie łuków i okręgów → (opcjonalnie) łączenie odcinków.
Tolerancje są wyrażone w pt na arkuszu i przeliczane przez ``unit_scale``,
więc zachowanie nie zależy od ``--units`` ani ``--scale``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, replace

from pdf2dxf.model import (
    ArcSeg,
    CubicSeg,
    LineSeg,
    PageData,
    Point,
    Segment,
    Shape,
    Style,
    SubPath,
    TextItem,
)

ROUND_DIGITS = 6
"""Zaokrąglenie współrzędnych (cyfry po przecinku w jednostkach DXF)."""
ZERO_LENGTH_TOL_PT = 0.005
"""Segmenty krótsze (pt na arkuszu, ≈ 0.002 mm) to szum numeryczny i są usuwane."""
FULL_CIRCLE_SLACK = 0.5
"""Zapas (°) przy łączeniu łuków w pełny okrąg (suma kątów z danych float32 bywa > 360°)."""
DEDUP_TOL_PT = 0.01
"""Siatka porównywania przy deduplikacji i łączeniu (pt na arkuszu)."""
ARC_ABS_TOL_PT = 0.005
"""Bezwzględna tolerancja wykrywania łuków (pt na arkuszu)."""
ARC_REL_TOL = 1e-3
"""Względna tolerancja wykrywania łuków (ułamek promienia)."""
ARC_MAX_SWEEP = 91.0
"""Największy kąt łuku (°) rozpoznawany z jednej krzywej Béziera."""
MERGE_MAX_GAP = 0.5
"""Maksymalna przerwa między łączonymi fragmentami tekstu (× rozmiar fontu)."""
MERGE_SPACE_GAP = 0.15
"""Przerwa, od której przy łączeniu wstawiana jest spacja (× rozmiar fontu)."""


@dataclass
class PostprocessOptions:
    detect_arcs: bool = True
    join: bool = False


@dataclass
class PostprocessStats:
    zero_length_removed: int = 0
    duplicates_removed: int = 0
    arcs_detected: int = 0
    joined: int = 0


def postprocess_page(
    page: PageData, options: PostprocessOptions | None = None
) -> tuple[PageData, PostprocessStats]:
    """Porządkuje geometrię strony (w przestrzeni DXF). Zwraca (nowa strona, statystyki)."""
    if page.space != "dxf":
        raise ValueError("postprocessing działa na stronie w przestrzeni DXF")
    opts = options or PostprocessOptions()
    stats = PostprocessStats()
    k = page.unit_scale
    shapes = [round_shape(s) for s in page.shapes]
    shapes, stats.zero_length_removed = remove_zero_length(shapes, ZERO_LENGTH_TOL_PT * k)
    shapes, stats.duplicates_removed = deduplicate(shapes, DEDUP_TOL_PT * k)
    if opts.detect_arcs:
        shapes, stats.arcs_detected = detect_arcs(shapes, ARC_ABS_TOL_PT * k)
    if opts.join:
        shapes, stats.joined = join_subpaths(shapes, DEDUP_TOL_PT * k)
    return replace(page, shapes=shapes), stats


# ---------------------------------------------------------------------------
# zaokrąglanie i odcinki zerowej długości
# ---------------------------------------------------------------------------


def _rp(p: Point) -> Point:
    return (round(p[0], ROUND_DIGITS) + 0.0, round(p[1], ROUND_DIGITS) + 0.0)


def round_segment(seg: Segment) -> Segment:
    if isinstance(seg, LineSeg):
        return LineSeg(_rp(seg.p1), _rp(seg.p2))
    if isinstance(seg, CubicSeg):
        return CubicSeg(_rp(seg.p1), _rp(seg.c1), _rp(seg.c2), _rp(seg.p2))
    return ArcSeg(_rp(seg.p1), _rp(seg.p2), _rp(seg.center), seg.sweep)


def round_shape(shape: Shape) -> Shape:
    """Zaokrągla współrzędne do ``ROUND_DIGITS`` miejsc (usuwa szum numeryczny)."""
    return replace(
        shape,
        subpaths=[SubPath([round_segment(s) for s in sp.segments], sp.closed)
                  for sp in shape.subpaths],
    )


def _is_zero_length(seg: Segment, tol: float) -> bool:
    if isinstance(seg, LineSeg):
        return math.dist(seg.p1, seg.p2) <= tol
    if isinstance(seg, CubicSeg):
        return all(math.dist(seg.p1, p) <= tol for p in (seg.c1, seg.c2, seg.p2))
    return math.dist(seg.p1, seg.p2) <= tol and abs(seg.sweep) < 1.0


def remove_zero_length(shapes: list[Shape], tol: float = 0.0) -> tuple[list[Shape], int]:
    """Usuwa segmenty o długości ≤ ``tol`` (szum numeryczny, np. odcinek zamykający
    po operatorze ``h``) oraz puste podścieżki i kształty.

    Po usunięciu segmentu sąsiednie są dociągane do siebie, więc podścieżka
    pozostaje ciągła.
    """
    removed = 0
    result: list[Shape] = []
    for shape in shapes:
        subpaths: list[SubPath] = []
        for sp in shape.subpaths:
            segs = [s for s in sp.segments if not _is_zero_length(s, tol)]
            if len(segs) != len(sp.segments):
                removed += len(sp.segments) - len(segs)
                segs = _reconnect(segs, sp.closed)
            if segs:
                subpaths.append(SubPath(segs, sp.closed and len(segs) > 1))
        if subpaths:
            result.append(replace(shape, subpaths=subpaths))
    return result, removed


def _reconnect(segs: list[Segment], closed: bool) -> list[Segment]:
    """Dociąga początek każdego segmentu do końca poprzedniego (i koniec do startu)."""
    out: list[Segment] = []
    for seg in segs:
        if out and seg.start != out[-1].end:
            seg = _with_start(seg, out[-1].end)
        out.append(seg)
    if closed and len(out) > 1 and out[-1].end != out[0].start:
        out[-1] = _with_end(out[-1], out[0].start)
    return out


# ---------------------------------------------------------------------------
# deduplikacja
# ---------------------------------------------------------------------------

_Key = tuple


def _q(p: Point, grid: float) -> tuple[int, int]:
    return (round(p[0] / grid), round(p[1] / grid))


def _seg_key(seg: Segment, grid: float) -> _Key:
    if isinstance(seg, LineSeg):
        return ("L", _q(seg.p1, grid), _q(seg.p2, grid))
    if isinstance(seg, CubicSeg):
        return ("C", _q(seg.p1, grid), _q(seg.c1, grid), _q(seg.c2, grid), _q(seg.p2, grid))
    return ("A", _q(seg.p1, grid), _q(seg.p2, grid), _q(seg.center, grid), round(seg.sweep, 3))


def _rotate_to_min(keys: list[_Key]) -> tuple[_Key, ...]:
    i = keys.index(min(keys))
    return tuple(keys[i:] + keys[:i])


def subpath_key(sp: SubPath, grid: float) -> _Key:
    """Klucz geometrii podścieżki niezależny od kierunku (i punktu startu, gdy zamknięta)."""
    fwd = [_seg_key(s, grid) for s in sp.segments]
    rev = [_seg_key(s.reversed(), grid) for s in reversed(sp.segments)]
    if sp.closed:
        return ("closed", min(_rotate_to_min(fwd), _rotate_to_min(rev)))
    return ("open", min(tuple(fwd), tuple(rev)))


def _segment_key_undirected(seg: Segment, grid: float) -> _Key:
    return min(_seg_key(seg, grid), _seg_key(seg.reversed(), grid))


def _style_key(shape: Shape) -> tuple[Style, bool, bool, bool]:
    return (shape.style, shape.stroked, shape.filled, shape.even_odd)


def deduplicate(shapes: list[Shape], grid: float) -> tuple[list[Shape], int]:
    """Usuwa powtórzoną geometrię o tym samym stylu.

    * kształty z wypełnieniem — całe, gdy wszystkie podścieżki się powtarzają;
    * kształty tylko z obrysem — pojedyncze podścieżki (niezależnie od kierunku),
      a także pojedyncze odcinki pokrywające się z bokiem innej polilinii.
    """
    removed = 0
    seen_paths: set[_Key] = set()
    seen_filled: set[_Key] = set()
    result: list[Shape] = []
    for shape in shapes:
        style = _style_key(shape)
        if shape.filled:
            key = (style, tuple(sorted(subpath_key(sp, grid) for sp in shape.subpaths)))
            if key in seen_filled:
                removed += 1
                continue
            seen_filled.add(key)
            result.append(shape)
            continue
        kept: list[SubPath] = []
        for sp in shape.subpaths:
            key = (style, subpath_key(sp, grid))
            if key in seen_paths:
                removed += 1
                continue
            seen_paths.add(key)
            kept.append(sp)
        if kept:
            result.append(replace(shape, subpaths=kept))

    # pojedyncze odcinki zdublowane przez boki polilinii o tym samym stylu
    edges: set[_Key] = set()
    for shape in result:
        if shape.filled:
            continue
        for sp in shape.subpaths:
            if len(sp.segments) > 1:
                style = _style_key(shape)
                edges.update((style, _segment_key_undirected(s, grid)) for s in sp.segments)
    if not edges:
        return result, removed
    final: list[Shape] = []
    for shape in result:
        if shape.filled:
            final.append(shape)
            continue
        style = _style_key(shape)
        kept = []
        for sp in shape.subpaths:
            if (len(sp.segments) == 1 and not sp.closed
                    and (style, _segment_key_undirected(sp.segments[0], grid)) in edges):
                removed += 1
                continue
            kept.append(sp)
        if kept:
            final.append(replace(shape, subpaths=kept))
    return final, removed


# ---------------------------------------------------------------------------
# łuki i okręgi
# ---------------------------------------------------------------------------


def _sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _bezier(seg: CubicSeg, t: float) -> Point:
    u = 1.0 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (
        a * seg.p1[0] + b * seg.c1[0] + c * seg.c2[0] + d * seg.p2[0],
        a * seg.p1[1] + b * seg.c1[1] + c * seg.c2[1] + d * seg.p2[1],
    )


def cubic_to_arc(
    seg: CubicSeg,
    abs_tol: float,
    rel_tol: float = ARC_REL_TOL,
    max_sweep: float = ARC_MAX_SWEEP,
) -> ArcSeg | None:
    """Zwraca łuk, jeśli krzywa Béziera przybliża łuk okręgu ≤ ``max_sweep`` stopni.

    Środek to przecięcie normalnych w punktach końcowych; sprawdzane są:
    równość promieni na końcach, odległość punktów krzywej (t = ¼, ½, ¾) od
    środka i długość ramion kontrolnych (``4/3·tan(θ/4)·r``).
    """
    p0, p3 = seg.p1, seg.p2
    t0, t1 = _sub(seg.c1, p0), _sub(p3, seg.c2)
    l0, l1 = math.hypot(*t0), math.hypot(*t1)
    if l0 <= abs_tol or l1 <= abs_tol or math.dist(p0, p3) <= abs_tol:
        return None
    n0, n1 = (-t0[1], t0[0]), (-t1[1], t1[0])
    det = _cross(n0, n1)
    if abs(det) <= 1e-9 * l0 * l1:
        return None  # styczne równoległe: prosta albo półokrąg
    a = _cross(_sub(p3, p0), n1) / det
    center = (p0[0] + a * n0[0], p0[1] + a * n0[1])
    v0, v1 = _sub(p0, center), _sub(p3, center)
    r0, r1 = math.hypot(*v0), math.hypot(*v1)
    r = (r0 + r1) / 2.0
    tol = max(rel_tol * r, abs_tol)
    if abs(r0 - r1) > tol:
        return None
    ccw = _cross(v0, t0) > 0
    if (_cross(v1, t1) > 0) != ccw:
        return None
    sweep = math.atan2(_cross(v0, v1), _dot(v0, v1))
    if ccw and sweep <= 0:
        sweep += 2 * math.pi
    elif not ccw and sweep >= 0:
        sweep -= 2 * math.pi
    if math.degrees(abs(sweep)) > max_sweep:
        return None
    for t in (0.25, 0.5, 0.75):
        if abs(math.dist(_bezier(seg, t), center) - r) > tol:
            return None
    handle = 4.0 / 3.0 * math.tan(abs(sweep) / 4.0) * r
    for length in (l0, l1):
        if abs(length - handle) > max(0.05 * handle, tol):
            return None
    return ArcSeg(p0, p3, center, math.degrees(sweep))


def _mergeable(a: Segment, b: Segment, tol: float) -> bool:
    return (
        isinstance(a, ArcSeg)
        and isinstance(b, ArcSeg)
        and (a.sweep > 0) == (b.sweep > 0)
        and math.dist(a.center, b.center) <= tol
        and abs(a.radius - b.radius) <= tol
        and abs(a.sweep + b.sweep) <= 360.0 + FULL_CIRCLE_SLACK
    )


def merge_arcs(segments: list[Segment], closed: bool, tol: float) -> list[Segment]:
    """Łączy kolejne łuki tego samego okręgu (także przez punkt startu zamkniętej ścieżki)."""
    segs = list(segments)
    if closed and len(segs) > 1 and _mergeable(segs[-1], segs[0], tol):
        # przesuń start tak, żeby nie wypadał w środku łuku
        i = len(segs) - 1
        while i > 0 and _mergeable(segs[i - 1], segs[i], tol):
            i -= 1
        if i > 0:
            segs = segs[i:] + segs[:i]
    out: list[Segment] = []
    for seg in segs:
        prev = out[-1] if out else None
        if prev is not None and _mergeable(prev, seg, tol):
            assert isinstance(prev, ArcSeg) and isinstance(seg, ArcSeg)
            out[-1] = ArcSeg(prev.p1, seg.p2, prev.center, prev.sweep + seg.sweep)
        else:
            out.append(seg)
    return out


def detect_arcs(shapes: list[Shape], abs_tol: float) -> tuple[list[Shape], int]:
    """Zamienia krzywe Béziera przybliżające łuki na :class:`ArcSeg` i łączy łuki."""
    found = 0
    result: list[Shape] = []
    for shape in shapes:
        subpaths: list[SubPath] = []
        for sp in shape.subpaths:
            if not any(isinstance(s, CubicSeg) for s in sp.segments):
                subpaths.append(sp)
                continue
            segs: list[Segment] = []
            for s in sp.segments:
                arc = cubic_to_arc(s, abs_tol) if isinstance(s, CubicSeg) else None
                if arc is not None:
                    found += 1
                    segs.append(arc)
                else:
                    segs.append(s)
            r_tol = max(abs_tol, ARC_REL_TOL * min(
                (s.radius for s in segs if isinstance(s, ArcSeg)), default=0.0))
            subpaths.append(SubPath(merge_arcs(segs, sp.closed, r_tol), sp.closed))
        result.append(replace(shape, subpaths=subpaths))
    return result, found


# ---------------------------------------------------------------------------
# łączenie odcinków (--join)
# ---------------------------------------------------------------------------


def join_subpaths(shapes: list[Shape], grid: float) -> tuple[list[Shape], int]:
    """Skleja otwarte podścieżki o wspólnych końcach i tym samym stylu w dłuższe.

    Łączenie przechodzi tylko przez węzły, w których spotykają się dokładnie
    dwa końce — przy rozgałęzieniach (T, X) wynik byłby przypadkowy.
    Zwraca (kształty, liczba podścieżek wchłoniętych w dłuższe).
    """
    pools: dict[Style, list[SubPath]] = defaultdict(list)
    order: list[Style] = []
    kept: list[Shape] = []
    for shape in shapes:
        if not shape.stroked or shape.filled:
            kept.append(shape)
            continue
        rest = [sp for sp in shape.subpaths if sp.closed]
        open_paths = [sp for sp in shape.subpaths if not sp.closed]
        if open_paths:
            if shape.style not in pools:
                order.append(shape.style)
            pools[shape.style].extend(open_paths)
        if rest:
            kept.append(replace(shape, subpaths=rest))
    joined_total = 0
    for style in order:
        chains, joined = _chain(pools[style], grid)
        joined_total += joined
        kept.append(Shape(subpaths=chains, style=style, stroked=True, filled=False))
    return kept, joined_total


def _chain(paths: list[SubPath], grid: float) -> tuple[list[SubPath], int]:
    ends: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, sp in enumerate(paths):
        ends[_q(sp.start, grid)].append(i)
        ends[_q(sp.end, grid)].append(i)
    used = [False] * len(paths)
    result: list[SubPath] = []
    joined = 0

    def next_at(node: tuple[int, int], current: int) -> int | None:
        ids = ends[node]
        if len(ids) != 2:
            return None
        other = ids[0] if ids[1] == current else ids[1]
        return None if used[other] or other == current else other

    for i, sp in enumerate(paths):
        if used[i]:
            continue
        used[i] = True
        segs: list[Segment] = list(sp.segments)
        count = 1
        # w przód od końca
        last = i
        while (j := next_at(_q(segs[-1].end, grid), last)) is not None:
            used[j] = True
            part = paths[j] if _q(paths[j].start, grid) == _q(segs[-1].end, grid) \
                else _reverse(paths[j])
            segs.extend(_snap(part.segments, segs[-1].end))
            last, count = j, count + 1
        # wstecz od początku
        first = i
        while (j := next_at(_q(segs[0].start, grid), first)) is not None:
            used[j] = True
            part = paths[j] if _q(paths[j].end, grid) == _q(segs[0].start, grid) \
                else _reverse(paths[j])
            segs[:0] = _snap_end(part.segments, segs[0].start)
            first, count = j, count + 1
        closed = count > 1 and _q(segs[0].start, grid) == _q(segs[-1].end, grid)
        if closed:
            segs[-1] = _with_end(segs[-1], segs[0].start)
        if count > 1:
            joined += count
        result.append(SubPath(segs, closed))
    return result, joined


def _reverse(sp: SubPath) -> SubPath:
    return SubPath([s.reversed() for s in reversed(sp.segments)], sp.closed)


def _with_start(seg: Segment, start: Point) -> Segment:
    if isinstance(seg, LineSeg):
        return LineSeg(start, seg.p2)
    if isinstance(seg, CubicSeg):
        return CubicSeg(start, seg.c1, seg.c2, seg.p2)
    return ArcSeg(start, seg.p2, seg.center, seg.sweep)


def _with_end(seg: Segment, end: Point) -> Segment:
    if isinstance(seg, LineSeg):
        return LineSeg(seg.p1, end)
    if isinstance(seg, CubicSeg):
        return CubicSeg(seg.p1, seg.c1, seg.c2, end)
    return ArcSeg(seg.p1, end, seg.center, seg.sweep)


def _snap(segs: list[Segment], start: Point) -> list[Segment]:
    """Dociąga początek pierwszego segmentu dokładnie do ``start``."""
    return [_with_start(segs[0], start), *segs[1:]]


def _snap_end(segs: list[Segment], end: Point) -> list[Segment]:
    """Dociąga koniec ostatniego segmentu dokładnie do ``end``."""
    return [*segs[:-1], _with_end(segs[-1], end)]


# ---------------------------------------------------------------------------
# tekst
# ---------------------------------------------------------------------------


def merge_texts(items: list[TextItem]) -> list[TextItem]:
    """Łączy kolejne fragmenty tekstu z jednej linii bazowej o tym samym stylu.

    Fragmenty muszą mieć ten sam font, rozmiar, kolor, krycie i kąt, leżeć na
    jednej linii bazowej i być oddalone o co najwyżej ``MERGE_MAX_GAP`` ×
    rozmiar fontu. Przy przerwie większej niż ``MERGE_SPACE_GAP`` × rozmiar
    wstawiana jest spacja.
    """
    result: list[TextItem] = []
    for item in items:
        if result:
            merged = _try_merge(result[-1], item)
            if merged is not None:
                result[-1] = merged
                continue
        result.append(item)
    return result


def _try_merge(a: TextItem, b: TextItem) -> TextItem | None:
    if (a.font, a.color, a.opacity, a.layer) != (b.font, b.color, b.opacity, b.layer):
        return None
    size = a.size
    if size <= 0 or a.width <= 0 or not math.isclose(size, b.size, rel_tol=1e-6):
        return None
    if abs((a.angle - b.angle + 180.0) % 360.0 - 180.0) > 0.5:
        return None
    ux, uy = math.cos(math.radians(a.angle)), math.sin(math.radians(a.angle))
    dx, dy = b.origin[0] - a.origin[0], b.origin[1] - a.origin[1]
    along = dx * ux + dy * uy
    across = ux * dy - uy * dx
    gap = along - a.width
    if abs(across) > 0.1 * size or not (-0.1 * size <= gap <= MERGE_MAX_GAP * size):
        return None
    space = (
        gap > MERGE_SPACE_GAP * size
        and not a.text.endswith(" ")
        and not b.text.startswith(" ")
    )
    return replace(a, text=a.text + (" " if space else "") + b.text, width=along + b.width)
