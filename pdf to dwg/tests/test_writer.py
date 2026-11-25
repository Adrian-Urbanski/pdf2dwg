"""Testy writera DXF na ręcznie zbudowanym modelu (bez PDF)."""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers import read_dxf
from pdf2dxf.model import LineSeg, PageData, Shape, Style, SubPath
from pdf2dxf.writer import DxfWriter, WriterOptions


def _page(*subpaths: SubPath, **shape_kw) -> PageData:
    return PageData(index=0, width=100, height=100, space="dxf",
                    shapes=[Shape(list(subpaths), Style(), **shape_kw)])


def _square(closed: bool = True) -> SubPath:
    pts = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
    return SubPath([LineSeg(a, b) for a, b in zip(pts, pts[1:])], closed=closed)


def test_line_and_polylines(tmp_path: Path) -> None:
    w = DxfWriter()
    counts = w.add_page(_page(
        SubPath([LineSeg((0, 0), (5, 5))]),
        _square(),
        SubPath([LineSeg((0, 0), (1, 0)), LineSeg((1, 0), (1, 1))]),
    ))
    assert counts == {"LINE": 1, "LWPOLYLINE": 2}
    w.save(tmp_path / "a.dxf")
    doc = read_dxf(tmp_path / "a.dxf")
    msp = doc.modelspace()
    closed = [e for e in msp.query("LWPOLYLINE") if e.closed]
    assert len(closed) == 1 and len(closed[0]) == 4
    opened = [e for e in msp.query("LWPOLYLINE") if not e.closed]
    assert len(opened) == 1 and len(opened[0]) == 3


@pytest.mark.parametrize(("units", "insunits", "measurement"), [
    ("mm", 4, 1), ("cm", 5, 1), ("m", 6, 1), ("in", 1, 0), ("pt", 0, 1),
])
def test_header_units(tmp_path: Path, units: str, insunits: int, measurement: int) -> None:
    w = DxfWriter(WriterOptions(units=units))
    w.save(tmp_path / "u.dxf")
    doc = read_dxf(tmp_path / "u.dxf")
    assert doc.header["$INSUNITS"] == insunits
    assert doc.header["$MEASUREMENT"] == measurement


def test_rejects_pdf_space_page() -> None:
    page = PageData(index=0, width=1, height=1)
    with pytest.raises(ValueError):
        DxfWriter().add_page(page)


def test_dxf_version(tmp_path: Path) -> None:
    w = DxfWriter(WriterOptions(dxf_version="R2018"))
    w.add_page(_page(_square()))
    w.save(tmp_path / "v.dxf")
    assert read_dxf(tmp_path / "v.dxf").dxfversion == "AC1032"
