"""Faza 5: podgląd PNG i wizualne porównanie PDF ↔ DXF (test 15)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pymupdf
import pytest

from conftest import MakePdf
from helpers import read_dxf
from pdf2dxf.cli import main
from pdf2dxf.converter import ConvertOptions, convert
from pdf2dxf.preview import render_png

pytest.importorskip("matplotlib")

MM = 25.4 / 72
DPI = 100


def _drawing(page: pymupdf.Page) -> None:
    page.draw_line((60, 60), (535, 60), width=2)
    page.draw_rect(pymupdf.Rect(60, 100, 250, 220), width=2)
    page.draw_circle((400, 180), 70, color=(0, 0, 1), width=2)
    page.draw_bezier((60, 400), (150, 250), (300, 550), (535, 400), color=(1, 0, 0), width=2)
    page.draw_line((60, 600), (535, 600), dashes="[12 6] 0", width=2)
    page.draw_rect(pymupdf.Rect(100, 650, 300, 780), color=None, fill=(0, 0.4, 0))
    page.draw_rect(pymupdf.Rect(350, 650, 535, 780), radius=0.25, width=2)
    page.draw_oval(pymupdf.Rect(380, 450, 520, 540), width=2)


def _dark_mask_pdf(pdf: Path) -> np.ndarray:
    with pymupdf.open(pdf) as doc:
        pix = doc[0].get_pixmap(dpi=DPI, alpha=False, colorspace=pymupdf.csGRAY)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)
    return img[:, :pix.width] < 160


def _dark_mask_png(png: Path) -> np.ndarray:
    from PIL import Image

    img = np.asarray(Image.open(png).convert("L"))
    return img < 160


def _dilate(mask: np.ndarray, r: int) -> np.ndarray:
    out = mask.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= np.roll(np.roll(mask, dy, axis=0), dx, axis=1)
    return out


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    return float((a & b).sum() / max(1, (a | b).sum()))


@pytest.mark.slow
@pytest.mark.parametrize("curves", ["spline", "polyline"])
def test_case15_visual_overlay(make_pdf: MakePdf, tmp_path: Path, curves: str) -> None:
    pdf = make_pdf(_drawing)
    out = tmp_path / "rys.dxf"
    convert(pdf, out, ConvertOptions(curves=curves))
    png = render_png(read_dxf(out), tmp_path / "rys.png",
                     extents=(0, 0, 595 * MM, 842 * MM),
                     size_inches=(595 / 72, 842 / 72), dpi=DPI)
    a, b = _dark_mask_pdf(pdf), _dark_mask_png(png)
    h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
    a, b = a[:h, :w], b[:h, :w]
    assert a.sum() > 1000 and b.sum() > 1000
    # tolerancja: maski porównywane po rozszerzeniu o 2 px (antyaliasing, zaokrąglenia)
    iou = _iou(_dilate(a, 2), _dilate(b, 2))
    assert iou > 0.9, f"IoU = {iou:.3f}"


def test_preview_option_writes_png(make_pdf: MakePdf, tmp_path: Path,
                                   capsys: pytest.CaptureFixture[str]) -> None:
    pdf = make_pdf(_drawing)
    out = tmp_path / "podglad.dxf"
    assert main([str(pdf), "-o", str(out), "--preview"]) == 0
    png = out.with_suffix(".png")
    assert png.is_file() and png.stat().st_size > 1000
    assert "podgląd:" in capsys.readouterr().out
    mask = _dark_mask_png(png)
    assert 0.001 < mask.mean() < 0.5  # coś narysowano, ale tło jest białe


def test_preview_per_page(make_pdf: MakePdf, tmp_path: Path) -> None:
    pdf = make_pdf(_drawing, _drawing, name="dwie.pdf")
    report = convert(pdf, str(tmp_path) + "/", ConvertOptions(preview=True))
    assert [p.name for p in report.previews] == ["dwie_p1.png", "dwie_p2.png"]
