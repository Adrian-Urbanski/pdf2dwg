"""Testy CLI uruchamianego jak przez użytkownika."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest

from conftest import MakePdf
from helpers import convert_one, read_dxf
from pdf2dxf.cli import build_parser, main, parse_pages


def test_help_lists_options(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for opt in ("--units", "--scale", "--curves", "--layers", "--fills", "--pages",
                "--single-file", "--no-detect-arcs", "--merge-text", "--preview"):
        assert opt in out


def test_python_dash_m_help() -> None:
    res = subprocess.run([sys.executable, "-m", "pdf2dxf", "--help"],
                         capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0
    assert "--units" in res.stdout


def test_bad_arguments_exit_code_2() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["x.pdf", "--units", "furlong"])
    assert exc.value.code == 2


@pytest.mark.parametrize(("spec", "expected"), [
    ("1", [1]),
    ("1,3-5", [1, 3, 4, 5]),
    ("2, 2,1", [1, 2]),
])
def test_parse_pages(spec: str, expected: list[int]) -> None:
    assert parse_pages(spec) == expected


@pytest.mark.parametrize("spec", ["0", "3-1", "a", "", "1-x"])
def test_parse_pages_invalid(spec: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_pages(spec)


MM = 25.4 / 72


def _line_pdf(make_pdf: MakePdf) -> Path:
    return make_pdf(lambda p: p.draw_line((100, 100), (200, 100)))


def test_case1_line_length_and_y_flip(make_pdf: MakePdf) -> None:
    _, doc = convert_one(_line_pdf(make_pdf))
    (line,) = doc.modelspace().query("LINE")
    start, end = line.dxf.start, line.dxf.end
    assert start.distance(end) == pytest.approx(35.2778, abs=1e-3)
    assert (start.x, start.y) == pytest.approx((100 * MM, (842 - 100) * MM))
    assert (end.x, end.y) == pytest.approx((200 * MM, (842 - 100) * MM))
    assert doc.header["$INSUNITS"] == 4


def test_case2_rect_closed_lwpolyline(make_pdf: MakePdf) -> None:
    pdf = make_pdf(lambda p: p.draw_rect(pymupdf.Rect(50, 200, 150, 260)))
    _, doc = convert_one(pdf)
    (pl,) = doc.modelspace().query("LWPOLYLINE")
    assert pl.closed and len(pl) == 4
    xs = sorted({round(x, 6) for x, *_ in pl.get_points()})
    assert xs == pytest.approx([50 * MM, 150 * MM])


def test_case7_scale(make_pdf: MakePdf) -> None:
    _, doc = convert_one(_line_pdf(make_pdf), scale=100)
    (line,) = doc.modelspace().query("LINE")
    assert line.dxf.start.distance(line.dxf.end) == pytest.approx(3527.78, abs=1e-2)
    assert line.dxf.start.y == pytest.approx((842 - 100) * MM * 100)


def test_case7_units_inches(make_pdf: MakePdf) -> None:
    _, doc = convert_one(_line_pdf(make_pdf), units="in")
    (line,) = doc.modelspace().query("LINE")
    assert line.dxf.start.distance(line.dxf.end) == pytest.approx(100 / 72, abs=1e-6)
    assert doc.header["$INSUNITS"] == 1


def test_main_converts_and_reports(make_pdf: MakePdf, capsys: pytest.CaptureFixture[str]) -> None:
    pdf = _line_pdf(make_pdf)
    out = pdf.parent / "wynik" / "rysunek.dxf"
    assert main([str(pdf), "-o", str(out)]) == 0
    read_dxf(out)
    text = capsys.readouterr().out
    assert "LINE 1" in text and "strona 1" in text


def test_default_output_next_to_pdf(make_pdf: MakePdf) -> None:
    pdf = _line_pdf(make_pdf)
    assert main([str(pdf)]) == 0
    read_dxf(pdf.with_suffix(".dxf"))


def test_output_directory(make_pdf: MakePdf, tmp_path: Path) -> None:
    pdf = _line_pdf(make_pdf)
    outdir = tmp_path / "katalog"
    assert main([str(pdf), "-o", str(outdir) + "/"]) == 0
    read_dxf(outdir / "test.dxf")


def test_missing_file_exit_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path / "brak.pdf")]) == 1
    assert "nie znaleziono" in capsys.readouterr().err


def test_not_a_pdf_exit_1(tmp_path: Path) -> None:
    bad = tmp_path / "zly.pdf"
    bad.write_text("to nie jest PDF", encoding="utf-8")
    assert main([str(bad)]) == 1


def test_defaults() -> None:
    ns = build_parser().parse_args(["a.pdf"])
    assert ns.units == "mm" and ns.scale == 1.0 and ns.curves == "spline"
    assert ns.detect_arcs is True and ns.join is False
    assert ns.layers == "by-color" and ns.fills == "hatch"
    assert ns.dxf_version == "R2010" and ns.text_height_factor == 0.7
