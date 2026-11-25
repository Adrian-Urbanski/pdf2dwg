"""Podgląd PNG wyrenderowany z DXF (opcjonalny, wymaga matplotlib).

Renderowany jest gotowy plik DXF (a nie PDF), więc podgląd pokazuje to, co
zobaczy program CAD: encje, kolory, grubości i kreskowania.
"""

from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf import bbox
from ezdxf.document import Drawing

Extents = tuple[float, float, float, float]
MM_TO_POINTS = 72.0 / 25.4


class PreviewUnavailable(RuntimeError):
    """Brak matplotlib — podgląd niedostępny."""


def render_png(
    doc: Drawing | str | Path,
    png_path: str | Path,
    *,
    extents: Extents | None = None,
    size_inches: tuple[float, float] | None = None,
    dpi: int = 100,
    max_pixels: int = 2000,
) -> Path:
    """Renderuje przestrzeń modelu DXF do PNG na białym tle.

    Args:
        doc: dokument ezdxf albo ścieżka pliku DXF.
        png_path: plik wynikowy.
        extents: obszar ``(x0, y0, x1, y1)`` w jednostkach rysunku; domyślnie
            zakres wszystkich encji z marginesem 2 %.
        size_inches: rozmiar obrazu; domyślnie dłuższy bok = ``max_pixels``
            pikseli przy podanym ``dpi``.
        dpi: rozdzielczość PNG.
    """
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
    except ImportError as exc:  # pragma: no cover - zależne od instalacji
        raise PreviewUnavailable(
            "podgląd wymaga matplotlib: pip install \"pdf2dxf[preview]\""
        ) from exc
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.config import (
        BackgroundPolicy,
        ColorPolicy,
        Configuration,
        LineweightPolicy,
    )
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    if not isinstance(doc, Drawing):
        doc = ezdxf.readfile(doc)
    msp = doc.modelspace()
    if extents is None:
        extents = _drawing_extents(doc)
    x0, y0, x1, y1 = extents
    w, h = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    if size_inches is None:
        scale = max_pixels / dpi / max(w, h)
        size_inches = (max(w * scale, 0.5), max(h * scale, 0.5))

    fig = Figure(figsize=size_inches, dpi=dpi)
    FigureCanvasAgg(fig)
    ax = fig.add_axes((0.0, 0.0, 1.0, 1.0))
    config = Configuration(
        background_policy=BackgroundPolicy.WHITE,
        color_policy=ColorPolicy.COLOR,
        lineweight_policy=LineweightPolicy.ABSOLUTE,
        # backend matplotlib w ezdxf 1.4 przekazuje lineweight w mm jako szerokość
        # linii w punktach — przeliczamy mm → pt, żeby grubości były jak na wydruku
        lineweight_scaling=MM_TO_POINTS,
    )
    backend = MatplotlibBackend(ax, adjust_figure=False)
    Frontend(RenderContext(doc), backend, config=config).draw_layout(msp, finalize=True)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("auto")
    ax.set_axis_off()
    out = Path(png_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, facecolor="white")
    return out


def render_preview(dxf_path: str | Path) -> Path:
    """Zapisuje podgląd ``<plik>.png`` obok pliku DXF i zwraca jego ścieżkę."""
    path = Path(dxf_path)
    return render_png(path, path.with_suffix(".png"))


def _drawing_extents(doc: Drawing) -> Extents:
    box = bbox.extents(doc.modelspace(), fast=True)
    if not box.has_data:
        return (0.0, 0.0, 1.0, 1.0)
    (x0, y0, _), (x1, y1, _) = box.extmin, box.extmax
    margin = 0.02 * max(x1 - x0, y1 - y0, 1e-9)
    return (x0 - margin, y0 - margin, x1 + margin, y1 + margin)
