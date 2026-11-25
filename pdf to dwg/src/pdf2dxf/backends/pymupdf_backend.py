"""Backend ekstrakcji oparty na PyMuPDF.

Struktury danych sprawdzone na PyMuPDF 1.28.2 (``scripts/recon_pymupdf.py``):
współrzędne ``get_drawings()``/``get_text()`` dotyczą strony nieobróconej,
liczone od lewego górnego rogu CropBox, oś Y w dół.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pymupdf

from pdf2dxf.backends.base import PdfBackend, PdfError
from pdf2dxf.model import (
    RGB,
    CubicSeg,
    DashPattern,
    LineSeg,
    PageData,
    Point,
    Segment,
    Shape,
    Style,
    SubPath,
    TextItem,
)

JOIN_TOL = 1e-3
"""Tolerancja (pt) ciągłości kolejnych elementów ścieżki i zamknięcia podścieżki."""

_DASH_RE = re.compile(r"\[\s*([^\]]*)\]\s*([-+0-9.eE]*)")


class PyMuPdfBackend(PdfBackend):
    """Dokument PDF otwarty przez PyMuPDF."""

    def __init__(self, path: Path) -> None:
        try:
            self._doc = pymupdf.open(path)
        except Exception as exc:  # PyMuPDF rzuca różne wyjątki dla złych plików
            raise PdfError(f"nie można otworzyć PDF {path}: {exc}") from exc
        if not self._doc.is_pdf:
            self._doc.close()
            raise PdfError(f"plik nie jest dokumentem PDF: {path}")
        if self._doc.needs_pass:
            self._doc.close()
            raise PdfError(f"PDF jest zabezpieczony hasłem: {path}")

    @property
    def page_count(self) -> int:
        return self._doc.page_count

    def extract_page(self, index: int, *, with_text: bool = True) -> PageData:
        page = self._doc[index]
        box = page.cropbox
        data = PageData(
            index=index,
            width=float(box.width),
            height=float(box.height),
            rotation=int(page.rotation) % 360,
        )
        for d in page.get_drawings():
            shape = drawing_to_shape(d)
            if shape is not None:
                data.shapes.append(shape)
        if with_text:
            data.texts, invisible, unmapped = extract_texts(page)
            if invisible:
                data.warnings.append(
                    f"pominięto {invisible} niewidocznych fragmentów tekstu (np. warstwa OCR)"
                )
            if unmapped:
                data.warnings.append(
                    f"{unmapped} fragmentów tekstu bez mapowania Unicode (znaki „�”)"
                )
        data.image_count, data.image_coverage = _image_stats(page, data.width, data.height)
        return data

    def render_png(self, index: int, max_width: int, max_height: int) -> bytes:
        page = self._doc[index]
        rect = page.rect  # wymiary po obrocie strony
        zoom = max(0.01, min(max_width / rect.width, max_height / rect.height))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png")

    def close(self) -> None:
        self._doc.close()


# ---------------------------------------------------------------------------
# ścieżki
# ---------------------------------------------------------------------------


def drawing_to_shape(d: dict[str, Any]) -> Shape | None:
    """Zamienia jeden słownik z ``page.get_drawings()`` na :class:`Shape`."""
    kind = d.get("type") or ""
    stroked = "s" in kind
    filled = "f" in kind
    if not (stroked or filled):
        return None
    subpaths = items_to_subpaths(d.get("items") or [], bool(d.get("closePath")))
    if not subpaths:
        return None
    width = d.get("width")
    style = Style(
        stroke_color=to_rgb(d.get("color")) if stroked else None,
        fill_color=to_rgb(d.get("fill")) if filled else None,
        line_width=0.0 if width is None else float(width),
        dashes=parse_dashes(d.get("dashes")) if stroked else None,
        layer=d.get("layer") or None,
        stroke_opacity=_opacity(d.get("stroke_opacity")),
        fill_opacity=_opacity(d.get("fill_opacity")),
    )
    return Shape(
        subpaths=subpaths,
        style=style,
        stroked=stroked,
        filled=filled,
        even_odd=bool(d.get("even_odd")),
    )


def items_to_subpaths(items: Iterable[Sequence[Any]], close_path: bool = False) -> list[SubPath]:
    """Dzieli elementy ścieżki PyMuPDF na ciągłe podścieżki.

    Nowa podścieżka zaczyna się, gdy początek elementu nie pokrywa się z końcem
    poprzedniego. ``re`` i ``qu`` to zawsze osobne, zamknięte podścieżki.
    ``close_path`` (flaga ``closePath``) zamyka ostatnią podścieżkę.
    """
    result: list[SubPath] = []
    current: list[Segment] = []

    def flush() -> None:
        if current:
            closed = _is_closed(current)
            if closed:  # dociągnij koniec dokładnie do początku
                current[-1] = _with_end(current[-1], current[0].start)
            result.append(SubPath(list(current), closed=closed))
            current.clear()

    for item in items:
        op = item[0]
        if op in ("re", "qu"):
            flush()
            result.append(SubPath(_polygon(_corner_points(item)), closed=True))
            continue
        if op == "l":
            seg: Segment = LineSeg(_pt(item[1]), _pt(item[2]))
        elif op == "c":
            seg = CubicSeg(_pt(item[1]), _pt(item[2]), _pt(item[3]), _pt(item[4]))
        else:  # nieznany element — pomijamy
            continue
        if current and not _close(current[-1].end, seg.start):
            flush()
        current.append(seg)
    flush()

    if close_path and result and not result[-1].closed:
        last = result[-1]
        if not _close(last.end, last.start):
            last.segments.append(LineSeg(last.end, last.start))
        last.closed = True
    return result


def _corner_points(item: Sequence[Any]) -> list[Point]:
    """Wierzchołki prostokąta (``re``) lub czworokąta (``qu``) po obwodzie.

    Orientacja ``re`` równa 1 oznacza obieg przeciwny do ruchu wskazówek zegara
    na ekranie (jak operator PDF ``re``): lewy dolny → prawy dolny → prawy górny
    → lewy górny (w układzie z osią Y w dół). Kierunek obiegu ma znaczenie dla
    reguły wypełniania nonzero.
    """
    if item[0] == "re":
        r = item[1]
        pts = [(r.x0, r.y1), (r.x1, r.y1), (r.x1, r.y0), (r.x0, r.y0)]
        orientation = item[2] if len(item) > 2 else 1
        if orientation == -1:
            pts = [pts[0], *reversed(pts[1:])]
        return [(float(x), float(y)) for x, y in pts]
    q = item[1]  # Quad: ul, ur, ll, lr — obwód to ul → ur → lr → ll
    return [_pt(q.ul), _pt(q.ur), _pt(q.lr), _pt(q.ll)]


def _polygon(points: list[Point]) -> list[Segment]:
    n = len(points)
    return [LineSeg(points[i], points[(i + 1) % n]) for i in range(n)]


def _is_closed(segments: list[Segment]) -> bool:
    if len(segments) == 1 and isinstance(segments[0], LineSeg):
        return False
    return _close(segments[0].start, segments[-1].end)


def _with_end(seg: Segment, end: Point) -> Segment:
    if isinstance(seg, LineSeg):
        return LineSeg(seg.p1, end)
    if isinstance(seg, CubicSeg):
        return CubicSeg(seg.p1, seg.c1, seg.c2, end)
    return seg


def _close(a: Point, b: Point) -> bool:
    return abs(a[0] - b[0]) <= JOIN_TOL and abs(a[1] - b[1]) <= JOIN_TOL


def _pt(p: Any) -> Point:
    return (float(p[0]), float(p[1]))


# ---------------------------------------------------------------------------
# tekst
# ---------------------------------------------------------------------------

_TEXT_FLAGS = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
_CHAR_VISIBLE = 16 | 32  # FZ_STEXT_FILLED | FZ_STEXT_STROKED


def extract_texts(page: pymupdf.Page) -> tuple[list[TextItem], int, int]:
    """Spany tekstu strony jako :class:`TextItem` (przestrzeń PDF).

    Zwraca (elementy, liczba pominiętych niewidocznych spanów, liczba spanów
    z niezmapowanymi znakami). Spany z samych białych znaków są pomijane.
    """
    items: list[TextItem] = []
    invisible = unmapped = 0
    for block in page.get_text("dict", flags=_TEXT_FLAGS)["blocks"]:
        if block.get("type", 0) != 0:
            continue
        for line in block.get("lines", []):
            dx, dy = line.get("dir", (1.0, 0.0))
            angle = math.degrees(math.atan2(dy, dx))
            for span in line.get("spans", []):
                text = clean_text(span.get("text", ""))
                if not text.strip():
                    continue
                if _is_invisible(span):
                    invisible += 1
                    continue
                if "�" in text:
                    unmapped += 1
                items.append(
                    TextItem(
                        text=text,
                        origin=_pt(span["origin"]),
                        size=float(span.get("size", 0.0)),
                        angle=angle,
                        font=str(span.get("font", "")),
                        color=int_to_rgb(int(span.get("color", 0))),
                        opacity=span.get("alpha", 255) / 255.0,
                        width=_span_advance(span, (dx, dy)),
                    )
                )
    return items, invisible, unmapped


def clean_text(text: str) -> str:
    """Usuwa znaki sterujące (tabulator → spacja), których nie może być w TEXT."""
    return "".join(" " if ch == "\t" else ch for ch in text if ch == "\t" or ord(ch) >= 32)


def int_to_rgb(value: int) -> RGB:
    """Kolor sRGB zapisany jako int (``0xRRGGBB``) → RGB 0–1."""
    return (((value >> 16) & 255) / 255.0, ((value >> 8) & 255) / 255.0, (value & 255) / 255.0)


def _is_invisible(span: dict[str, Any]) -> bool:
    if span.get("alpha", 255) == 0:
        return True
    flags = span.get("char_flags")
    return flags is not None and not flags & _CHAR_VISIBLE


def _span_advance(span: dict[str, Any], direction: tuple[float, float]) -> float:
    """Długość spanu wzdłuż kierunku tekstu, odtworzona z prostokąta otaczającego.

    Dla tekstu obróconego bbox jest obwiednią osiową:
    ``w_bb = W·|cos| + H·|sin|``, ``h_bb = W·|sin| + H·|cos|``.
    """
    x0, y0, x1, y1 = span.get("bbox", (0, 0, 0, 0))
    wb, hb = max(0.0, x1 - x0), max(0.0, y1 - y0)
    c, s = abs(direction[0]), abs(direction[1])
    size = float(span.get("size", 0.0))
    height = size * (span.get("ascender", 1.0) - span.get("descender", 0.0))
    if c >= s:
        return max(0.0, (wb - height * s) / c) if c > 1e-9 else 0.0
    return max(0.0, (hb - height * c) / s)


# ---------------------------------------------------------------------------
# styl
# ---------------------------------------------------------------------------


def parse_dashes(value: str | None) -> DashPattern | None:
    """Parsuje wzór kresek PyMuPDF (napis PDF, np. ``"[ 6 3 ] 0"``).

    Zwraca ``None`` dla linii ciągłej (``"[] 0"``, ``None``, same zera).
    """
    if not value:
        return None
    m = _DASH_RE.search(value)
    if not m:
        return None
    try:
        lengths = tuple(abs(float(v)) for v in m.group(1).replace(",", " ").split())
        phase = float(m.group(2)) if m.group(2) else 0.0
    except ValueError:
        return None
    if not lengths or not any(lengths):
        return None
    if len(lengths) % 2:  # PDF: nieparzysta liczba wartości się powtarza
        lengths = lengths * 2
    return DashPattern(lengths, phase)


def to_rgb(color: Sequence[float] | None) -> RGB | None:
    """Kolor z PyMuPDF (szarość, RGB lub CMYK, składowe 0–1) → RGB."""
    if color is None:
        return None
    c = [min(1.0, max(0.0, float(v))) for v in color]
    if len(c) == 1:
        return (c[0], c[0], c[0])
    if len(c) == 3:
        return (c[0], c[1], c[2])
    if len(c) == 4:
        cy, m, y, k = c
        return ((1 - cy) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return None


def _opacity(value: float | None) -> float:
    return 1.0 if value is None else float(value)


def _image_stats(page: pymupdf.Page, width: float, height: float) -> tuple[int, float]:
    """Liczba obrazów na stronie i (przybliżony) ułamek powierzchni strony przez nie zakryty.

    Pola obrazów są sumowane bez odejmowania nakładania się (wynik obcięty do 1).
    """
    infos = page.get_image_info()
    page_area = width * height
    if page_area <= 0:
        return len(infos), 0.0
    clip = pymupdf.Rect(0, 0, width, height)
    area = 0.0
    for info in infos:
        visible = pymupdf.Rect(info.get("bbox", (0, 0, 0, 0))) & clip
        if not visible.is_empty:
            area += visible.width * visible.height
    coverage = area / page_area
    return len(infos), min(1.0, coverage) if math.isfinite(coverage) else 0.0
