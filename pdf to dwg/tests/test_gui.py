"""Faza 7: logika okna (bez klikania) i test dymny samego okna."""

from __future__ import annotations

import time
from pathlib import Path

import ezdxf
import pymupdf
import pytest
from ezdxf.addons import odafc

from conftest import MakePdf
from pdf2dxf import dwg, gui
from pdf2dxf.gui import GuiSettings, parse_scale, pdf_paths, run_job


@pytest.mark.parametrize(("text", "value"), [
    ("1", 1.0), ("50", 50.0), ("1:50", 50.0), ("1/100", 100.0), (" 1 : 20 ", 20.0),
    ("2,5", 2.5), ("2:1", 0.5),
])
def test_parse_scale(text: str, value: float) -> None:
    assert parse_scale(text) == pytest.approx(value)


@pytest.mark.parametrize("text", ["", "abc", "0", "-5", "1:0", "1:-2"])
def test_parse_scale_invalid(text: str) -> None:
    with pytest.raises((ValueError, ZeroDivisionError)):
        parse_scale(text)


def test_pdf_paths(tmp_path: Path) -> None:
    pdf = tmp_path / "Rysunek.PDF"
    pdf.write_bytes(b"%PDF-1.7")
    txt = tmp_path / "notatka.txt"
    txt.write_text("x", encoding="utf-8")
    pdfs, rejected = pdf_paths([str(pdf), str(txt), str(tmp_path / "brak.pdf"), str(tmp_path)])
    assert pdfs == [pdf]
    assert len(rejected) == 3


# --- run_job ------------------------------------------------------------------------------


@pytest.fixture
def fake_oda(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Atrapa ODA: znaleziony program + odafc.convert zapisujący plik DWG."""
    exe = tmp_path / "oda" / "ODAFileConverter.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    monkeypatch.setenv(dwg.ENV_VAR, str(exe))

    def convert(source, dest="", *, version="R2018", audit=True, replace=False):
        Path(dest).write_bytes(b"AC1032" + b"\0" * 32)

    monkeypatch.setattr(odafc, "convert", convert)
    saved = {k: ezdxf.options.get("odafc-addon", k) for k in ("win_exec_path", "unix_exec_path")}
    yield exe
    for key, value in saved.items():  # dxf_to_dwg zmienia globalne ustawienia ezdxf
        ezdxf.options.set("odafc-addon", key, value)


@pytest.fixture
def no_oda(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(dwg, "find_converter", lambda explicit=None, **kw: None)


def _pdf(make_pdf: MakePdf) -> Path:
    return make_pdf(lambda p: p.draw_line((100, 100), (200, 100)), name="Detal 1.pdf")


def test_run_job_dwg_only(make_pdf: MakePdf, fake_oda: Path) -> None:
    pdf = _pdf(make_pdf)
    result = run_job(pdf, GuiSettings())
    assert result.ok
    assert result.outputs == [pdf.with_suffix(".dwg")]
    assert pdf.with_suffix(".dwg").is_file()
    assert not pdf.with_suffix(".dxf").exists()  # DXF pośredni usunięty
    assert "DWG:" in result.text


def test_run_job_keep_dxf_and_scale(make_pdf: MakePdf, fake_oda: Path) -> None:
    pdf = _pdf(make_pdf)
    result = run_job(pdf, GuiSettings(keep_dxf=True, scale=50, units="m"))
    assert result.ok
    assert sorted(p.suffix for p in result.outputs) == [".dwg", ".dxf"]
    doc = ezdxf.readfile(pdf.with_suffix(".dxf"))
    (line,) = doc.modelspace().query("LINE")
    assert line.dxf.start.distance(line.dxf.end) == pytest.approx(100 * 0.0254 / 72 * 50)
    assert doc.header["$INSUNITS"] == 6


def test_run_job_without_oda_keeps_dxf(make_pdf: MakePdf, no_oda: None) -> None:
    pdf = _pdf(make_pdf)
    result = run_job(pdf, GuiSettings())
    assert not result.ok
    assert result.outputs == [pdf.with_suffix(".dxf")] and pdf.with_suffix(".dxf").is_file()
    assert "ODA File Converter" in result.text and "zapisano tylko DXF" in result.text


def test_run_job_bad_file_does_not_raise(tmp_path: Path, no_oda: None) -> None:
    bad = tmp_path / "zly.pdf"
    bad.write_text("nie PDF", encoding="utf-8")
    result = run_job(bad, GuiSettings())
    assert not result.ok and "błąd" in result.text


def test_run_job_scan(make_pdf: MakePdf, no_oda: None) -> None:
    import pymupdf

    def image_only(page: pymupdf.Page) -> None:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20), False)
        pix.clear_with(128)
        page.insert_image(page.rect, pixmap=pix)

    result = run_job(make_pdf(image_only), GuiSettings())
    assert not result.ok and "skan" in result.text


# --- okno (test dymny) ----------------------------------------------------------------------


@pytest.fixture
def window():
    """Okno aplikacji (ukryte); pomijane bez środowiska graficznego."""
    import tkinter as tk

    try:
        root, dnd = gui._make_root()
    except tk.TclError as exc:  # brak ekranu (np. serwer CI)
        pytest.skip(f"brak środowiska graficznego: {exc}")
    root.withdraw()
    app = gui.App(root, dnd)
    root.update()
    yield app
    root.destroy()


def _wait_idle(app: gui.App, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while (app.busy or not app.jobs.empty()) and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.02)
    app.root.update()


def test_window_waits_for_convert_button(window: gui.App, make_pdf: MakePdf,
                                         fake_oda: Path) -> None:
    app = window
    assert "✓" in app.oda_label.cget("text")
    assert str(app.convert_btn.cget("state")) == "disabled"  # pusta lista
    pdf = _pdf(make_pdf)
    app.add_files([str(pdf)])
    for _ in range(20):  # dodanie pliku NIE uruchamia konwersji
        app.root.update()
        time.sleep(0.01)
    assert not app.busy and not pdf.with_suffix(".dwg").exists()
    assert [e.status for e in app.files] == ["pending"]
    assert str(app.convert_btn.cget("state")) == "normal"

    app.scale.set("1:10")
    app.convert_files()
    _wait_idle(app)
    log = app.log.get("1.0", "end")
    assert pdf.with_suffix(".dwg").is_file(), log
    assert "DWG:" in log
    assert [e.status for e in app.files] == ["ok"]
    assert app.listbox.get(0).strip().startswith("✓")
    assert str(app.open_btn.cget("state")) == "normal"

    app.scale.set("zła")
    app.convert_files()
    assert "niepoprawna skala" in app.log.get("1.0", "end")


def test_window_list_rules(window: gui.App, make_pdf: MakePdf, fake_oda: Path) -> None:
    app = window
    a = make_pdf(lambda p: p.draw_line((0, 0), (50, 50)), name="a.pdf")
    b = make_pdf(lambda p: p.draw_line((0, 0), (60, 60)), name="b.pdf")
    app.add_files([str(a), str(a)])          # duplikat dodaje się raz
    assert [e.path for e in app.files] == [a]
    app.convert_files()
    _wait_idle(app)
    assert app.files[0].status == "ok"
    app.add_files([str(b)])                  # nowy plik usuwa z listy gotowe (✓)
    assert [e.path for e in app.files] == [b]
    app.convert_files()
    _wait_idle(app)
    a_time = b.with_suffix(".dwg").stat().st_mtime_ns
    app.convert_files()                      # wszystkie gotowe → ponowna konwersja
    _wait_idle(app)
    assert b.with_suffix(".dwg").stat().st_mtime_ns >= a_time
    assert app.files[0].status == "ok"
    app.listbox.selection_set(0)
    app.remove_selected()
    assert app.files == [] and str(app.convert_btn.cget("state")) == "disabled"


def test_window_preview(window: gui.App, make_pdf: MakePdf) -> None:
    app = window
    app.root.geometry("1000x700")
    app.root.update()
    assert app._photo is None and "Podgląd" in app.canvas.itemcget(app.canvas.find_all()[0],
                                                                   "text")
    pdf = make_pdf(lambda p: p.draw_rect(pymupdf.Rect(50, 50, 300, 300)),
                   lambda p: p.draw_circle((200, 200), 80), name="dwie strony.pdf")
    app.add_files([str(pdf)])
    app.root.update()
    assert app._photo is not None
    assert "strona 1 z 2" in app.page_label.cget("text")
    assert str(app.next_btn.cget("state")) == "normal"
    app.turn_page(1)
    assert "strona 2 z 2" in app.page_label.cget("text")
    w, h = app._photo.width(), app._photo.height()
    assert 0 < w <= app.canvas.winfo_width() and 0 < h <= app.canvas.winfo_height()
    app.clear_files()
    assert app._photo is None and app.page_label.cget("text") == ""


def test_window_preview_broken_pdf(window: gui.App, tmp_path: Path) -> None:
    bad = tmp_path / "uszkodzony.pdf"
    bad.write_bytes(b"%PDF-1.7 to nie jest prawdziwy PDF")
    window.add_files([str(bad)])
    window.root.update()
    texts = [window.canvas.itemcget(i, "text") for i in window.canvas.find_all()]
    assert any("Nie można wyświetlić podglądu" in t for t in texts)


def test_drop_event_with_spaces_in_paths(make_pdf: MakePdf, monkeypatch: pytest.MonkeyPatch,
                                         tmp_path: Path) -> None:
    """tkdnd przekazuje ścieżki ze spacjami w nawiasach klamrowych: ``{C:/a b.pdf} C:/c.pdf``."""
    import tkinter as tk

    try:
        root, dnd = gui._make_root()
    except tk.TclError as exc:
        pytest.skip(f"brak środowiska graficznego: {exc}")
    try:
        root.withdraw()
        app = gui.App(root, dnd)
        received: list[list[str]] = []
        monkeypatch.setattr(app, "add_files", lambda items: received.append(items))
        a = tmp_path / "Rysunek z spacją.pdf"
        b = tmp_path / "drugi.pdf"

        class Event:
            data = "{" + a.as_posix() + "} " + b.as_posix()
            action = "copy"

        assert app._on_drop(Event()) == "copy"
        assert [Path(p) for p in received[0]] == [a, b]
    finally:
        root.destroy()
