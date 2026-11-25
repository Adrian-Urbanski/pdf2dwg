"""Faza 6: DXF → DWG przez ODA File Converter.

Prawdziwy konwerter rzadko jest zainstalowany na maszynie testowej, więc
logika jest testowana z atrapą ``ezdxf.addons.odafc.convert``; test
integracyjny uruchamia się tylko, gdy ODA File Converter zostanie znaleziony.
"""

from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest
from ezdxf.addons import odafc

from conftest import MakePdf
from pdf2dxf import dwg
from pdf2dxf.cli import main
from pdf2dxf.converter import ConvertOptions, convert
from pdf2dxf.dwg import ConverterNotFound, DwgError, dxf_to_dwg, find_converter


_ODAFC_KEYS = ("win_exec_path", "unix_exec_path")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Testy nie widzą prawdziwej instalacji ODA ani zmiennej środowiskowej.

    Ustawienia ezdxf (globalne) są przywracane po teście.
    """
    saved = {k: ezdxf.options.get("odafc-addon", k) for k in _ODAFC_KEYS}
    monkeypatch.delenv(dwg.ENV_VAR, raising=False)
    monkeypatch.setattr(dwg.shutil, "which", lambda name: None)
    monkeypatch.setattr(dwg, "_default_search_roots", lambda: [tmp_path / "brak"])
    ezdxf.options.set("odafc-addon", "win_exec_path", str(tmp_path / "brak.exe"))
    ezdxf.options.set("odafc-addon", "unix_exec_path", "")
    yield
    for key, value in saved.items():
        ezdxf.options.set("odafc-addon", key, value)


def _fake_exe(folder: Path, name: str = "ODAFileConverter.exe") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / name
    exe.write_bytes(b"MZ")
    return exe


class FakeOdafc:
    """Atrapa ``odafc.convert``: zapisuje plik z nagłówkiem DWG i zapamiętuje wywołania."""

    def __init__(self, create: bool = True) -> None:
        self.calls: list[dict] = []
        self.create = create

    def __call__(self, source, dest="", *, version="R2018", audit=True, replace=False):
        self.calls.append({"source": Path(source), "dest": Path(dest), "version": version,
                           "replace": replace, "exe": odafc.get_win_exec_path()})
        if self.create:
            Path(dest).write_bytes(b"AC1032" + b"\0" * 64)


# --- wyszukiwanie programu -------------------------------------------------------------


def test_find_converter_explicit_file_and_folder(tmp_path: Path) -> None:
    exe = _fake_exe(tmp_path / "oda")
    assert find_converter(exe) == exe
    assert find_converter(tmp_path / "oda") == exe
    assert find_converter(tmp_path / "nie_ma") is None


def test_find_converter_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exe = _fake_exe(tmp_path / "gdzies")
    monkeypatch.setenv(dwg.ENV_VAR, str(exe))
    assert find_converter() == exe


def test_find_converter_versioned_program_files(tmp_path: Path) -> None:
    root = tmp_path / "Program Files"
    _fake_exe(root / "ODA" / "ODAFileConverter 25.4.0")
    newest = _fake_exe(root / "ODA" / "ODAFileConverter 26.10.0")
    _fake_exe(root / "ODA" / "ODAFileConverter 26.2.0")
    assert find_converter(search_roots=[root]) == newest


def test_find_converter_none(tmp_path: Path) -> None:
    assert find_converter(search_roots=[tmp_path]) is None


# --- konwersja ------------------------------------------------------------------------------


def _dxf(tmp_path: Path) -> Path:
    doc = ezdxf.new("R2010")
    doc.modelspace().add_line((0, 0), (10, 0))
    path = tmp_path / "rys.dxf"
    doc.saveas(path)
    return path


def test_dxf_to_dwg_uses_found_converter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exe = _fake_exe(tmp_path / "oda")
    fake = FakeOdafc()
    monkeypatch.setattr(odafc, "convert", fake)
    out = dxf_to_dwg(_dxf(tmp_path), version="R2013", converter=exe)
    assert out == tmp_path / "rys.dwg" and out.read_bytes().startswith(b"AC10")
    (call,) = fake.calls
    assert call["version"] == "R2013" and call["replace"] is True
    if dwg.platform.system() == "Windows":
        assert call["exe"] == str(exe)  # ścieżka przekazana do ezdxf


def test_dxf_to_dwg_without_converter(tmp_path: Path) -> None:
    with pytest.raises(ConverterNotFound) as exc:
        dxf_to_dwg(_dxf(tmp_path))
    msg = str(exc.value)
    assert dwg.ODA_URL in msg and "--oda-path" in msg and dwg.ENV_VAR in msg


def test_dxf_to_dwg_no_output_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # ezdxf 1.4.5 nie rzuca wyjątku, gdy ODA nie utworzy pliku — wykrywamy to sami
    monkeypatch.setattr(odafc, "convert", FakeOdafc(create=False))
    with pytest.raises(DwgError, match="nie utworzył"):
        dxf_to_dwg(_dxf(tmp_path), converter=_fake_exe(tmp_path / "oda"))


def test_dxf_to_dwg_odafc_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args, **kwargs):
        raise odafc.UnknownODAFCError("coś poszło nie tak")

    monkeypatch.setattr(odafc, "convert", broken)
    with pytest.raises(DwgError, match="coś poszło nie tak"):
        dxf_to_dwg(_dxf(tmp_path), converter=_fake_exe(tmp_path / "oda"))


# --- potok i CLI ------------------------------------------------------------------------------


def _line_pdf(make_pdf: MakePdf, *draws) -> Path:
    return make_pdf(*(draws or (lambda p: p.draw_line((100, 100), (200, 100)),)))


def test_cli_dwg_success(make_pdf: MakePdf, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                         capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeOdafc()
    monkeypatch.setattr(odafc, "convert", fake)
    exe = _fake_exe(tmp_path / "oda")
    pdf = _line_pdf(make_pdf)
    assert main([str(pdf), "--dwg", "--dwg-version", "R2010", "--oda-path", str(exe)]) == 0
    assert pdf.with_suffix(".dxf").is_file() and pdf.with_suffix(".dwg").is_file()
    assert fake.calls[0]["version"] == "R2010"
    assert "DWG:" in capsys.readouterr().out


def test_cli_dwg_missing_converter_keeps_dxf(make_pdf: MakePdf,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    pdf = _line_pdf(make_pdf)
    assert main([str(pdf), "--dwg"]) == 1
    assert pdf.with_suffix(".dxf").is_file()
    assert not pdf.with_suffix(".dwg").exists()
    err = capsys.readouterr().err
    assert "ODA File Converter" in err and dwg.ODA_URL in err


def test_dwg_for_each_page(make_pdf: MakePdf, tmp_path: Path,
                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(odafc, "convert", FakeOdafc())
    pdf = make_pdf(lambda p: p.draw_line((0, 0), (9, 9)), lambda p: p.draw_line((0, 0), (5, 5)),
                   name="dwie.pdf")
    report = convert(pdf, str(tmp_path / "o") + "/",
                     ConvertOptions(dwg=True, oda_path=str(_fake_exe(tmp_path / "oda"))))
    assert [p.name for p in report.dwg_outputs] == ["dwie_p1.dwg", "dwie_p2.dwg"]
    assert not report.dwg_errors


def test_dwg_version_choices() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["a.pdf", "--dwg", "--dwg-version", "R12"])
    assert exc.value.code == 2


# --- integracja z prawdziwym ODA (pomijana, gdy programu nie ma) ---------------------------------


@pytest.mark.slow
def test_real_oda_conversion(make_pdf: MakePdf, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # bez izolacji: szukamy prawdziwej instalacji
    exe = dwg.find_converter()
    if exe is None:
        pytest.skip("ODA File Converter nie jest zainstalowany")
    pdf = _line_pdf(make_pdf)
    dwg_file = dxf_to_dwg(convert(pdf, None, ConvertOptions()).outputs[0], version="R2018")
    assert dwg_file.read_bytes()[:6] == b"AC1032"
    back = odafc.readfile(dwg_file)
    assert len(back.modelspace().query("LINE")) == 1
