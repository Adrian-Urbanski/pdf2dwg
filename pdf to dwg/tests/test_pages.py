"""Faza 4: wiele stron, strony obrócone, wykrywanie skanów (testy 10, 11, 13)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pymupdf
import pytest

from conftest import MakePdf
from helpers import read_dxf
from pdf2dxf.cli import main
from pdf2dxf.converter import ConvertOptions, convert

MM = 25.4 / 72


# --- test 10: strona obrócona = wygląd w przeglądarce ------------------------------------


def _dark_bbox(page: pymupdf.Page) -> tuple[float, float, float, float]:
    """Prostokąt ciemnych pikseli strony wyrenderowanej tak, jak w przeglądarce (72 dpi)."""
    pix = page.get_pixmap(dpi=72, alpha=False, colorspace=pymupdf.csGRAY)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]
    ys, xs = np.nonzero(img < 128)
    return float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_case10_rotated_page_matches_viewer(make_pdf: MakePdf, rotation: int) -> None:
    # Niesymetrycznie położony, wypełniony prostokąt — łatwo porównać z renderem.
    pdf = make_pdf(lambda p: p.draw_rect(pymupdf.Rect(60, 100, 200, 150), color=None,
                                         fill=(0, 0, 0)), rotation=rotation)
    out = pdf.with_suffix(".dxf")
    convert(pdf, out, ConvertOptions())
    (hatch,) = read_dxf(out).modelspace().query("HATCH")
    xs = [x for x, *_ in hatch.paths[0].vertices]
    ys = [y for _, y, *_ in hatch.paths[0].vertices]

    with pymupdf.open(pdf) as doc:
        page = doc[0]
        view_h = page.rect.height  # wysokość strony po obrocie (pt)
        px0, py0, px1, py1 = _dark_bbox(page)
    # DXF (mm, oś Y w górę) → piksele widoku (pt, oś Y w dół)
    dx0, dx1 = min(xs) / MM, max(xs) / MM
    dy0, dy1 = view_h - max(ys) / MM, view_h - min(ys) / MM
    assert (dx0, dy0, dx1, dy1) == pytest.approx((px0, py0, px1, py1), abs=1.5)


def test_rotated_page_dimensions(make_pdf: MakePdf) -> None:
    pdf = make_pdf(lambda p: p.draw_line((100, 100), (200, 100)), rotation=90)
    out = pdf.with_suffix(".dxf")
    convert(pdf, out, ConvertOptions(units="pt"))
    (line,) = read_dxf(out).modelspace().query("LINE")
    # strona 595×842 obrócona: widok 842×595; pozioma linia z lewego górnego rogu
    # staje się pionową linią przy prawym górnym rogu
    assert sorted([line.dxf.start.y, line.dxf.end.y]) == pytest.approx([495 - 100, 495])
    assert line.dxf.start.x == pytest.approx(742) and line.dxf.end.x == pytest.approx(742)


# --- test 11: skan -------------------------------------------------------------------------


def _image_only(page: pymupdf.Page) -> None:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
    pix.clear_with(180)
    page.insert_image(page.rect, pixmap=pix)


def test_case11_image_only_exit_3(make_pdf: MakePdf, capsys: pytest.CaptureFixture[str]) -> None:
    pdf = make_pdf(_image_only)
    assert main([str(pdf)]) == 3
    captured = capsys.readouterr()
    assert "skan" in captured.err
    assert "skan" in captured.out  # ostrzeżenie przy stronie w raporcie
    assert not pdf.with_suffix(".dxf").exists()


def test_scan_page_skipped_in_mixed_document(make_pdf: MakePdf, tmp_path: Path) -> None:
    pdf = make_pdf(lambda p: p.draw_line((10, 10), (100, 10)), _image_only)
    report = convert(pdf, str(tmp_path / "out") + "/", ConvertOptions())
    assert [p.raster for p in report.pages] == [False, True]
    assert report.outputs == [tmp_path / "out" / "test_p1.dxf"]
    assert not report.no_vector_data


def test_vector_page_with_logo_is_not_a_scan(make_pdf: MakePdf) -> None:
    def draw(page: pymupdf.Page) -> None:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10), False)
        pix.clear_with(0)
        page.insert_image(pymupdf.Rect(10, 10, 60, 60), pixmap=pix)
        for i in range(10):
            page.draw_line((100, 100 + 10 * i), (300, 100 + 10 * i))

    pdf = make_pdf(draw)
    report = convert(pdf, None, ConvertOptions())
    assert not report.pages[0].raster
    assert report.pages[0].entities == {"LINE": 10}
    assert any("obrazy" in w for w in report.pages[0].warnings)


def test_blank_pdf_exit_3_without_scan_message(make_pdf: MakePdf,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(make_pdf())]) == 3
    err = capsys.readouterr().err
    assert "danych wektorowych" in err and "skan" not in err


# --- test 13: wiele stron ------------------------------------------------------------------


def _page_with(n: int):
    def draw(page: pymupdf.Page) -> None:
        for i in range(n):
            page.draw_line((50, 50 + 20 * i), (150, 50 + 20 * i))
    return draw


def _three_pages(make_pdf: MakePdf) -> Path:
    return make_pdf(_page_with(1), _page_with(2), _page_with(3), name="plan.pdf")


def test_case13_one_file_per_page(make_pdf: MakePdf) -> None:
    pdf = _three_pages(make_pdf)
    assert main([str(pdf)]) == 0
    for n in (1, 2, 3):
        doc = read_dxf(pdf.parent / f"plan_p{n}.dxf")
        assert len(doc.modelspace().query("LINE")) == n


def test_case13_pages_option(make_pdf: MakePdf, tmp_path: Path) -> None:
    pdf = _three_pages(make_pdf)
    out = tmp_path / "wyniki"
    assert main([str(pdf), "-o", str(out) + "/", "--pages", "1,3"]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["plan_p1.dxf", "plan_p3.dxf"]
    assert main([str(pdf), "-o", str(tmp_path / "druga.dxf"), "--pages", "2"]) == 0
    assert len(read_dxf(tmp_path / "druga.dxf").modelspace().query("LINE")) == 2


def test_case13_missing_pages(make_pdf: MakePdf, tmp_path: Path,
                              capsys: pytest.CaptureFixture[str]) -> None:
    pdf = _three_pages(make_pdf)
    assert main([str(pdf), "-o", str(tmp_path) + "/", "--pages", "3-5"]) == 0
    assert "nieistniejące strony: 4, 5" in capsys.readouterr().out
    assert main([str(pdf), "--pages", "7"]) == 2


def test_case13_single_file(make_pdf: MakePdf, tmp_path: Path) -> None:
    pdf = _three_pages(make_pdf)
    out = tmp_path / "razem.dxf"
    assert main([str(pdf), "-o", str(out), "--single-file"]) == 0
    lines = read_dxf(out).modelspace().query("LINE")
    assert len(lines) == 6
    page_w = 595 * MM
    xs = sorted({round(e.dxf.start.x, 6) for e in lines})
    assert xs == pytest.approx([50 * MM, 50 * MM + 1.1 * page_w, 50 * MM + 2.2 * page_w])
