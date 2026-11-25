"""Konwersja gotowego DXF → DWG przez ODA File Converter (opcjonalna).

ODA File Converter to darmowy program Open Design Alliance, instalowany
osobno. Konwersję wykonuje :mod:`ezdxf.addons.odafc`; ten moduł dodaje
wyszukiwanie programu (nowsze instalatory ODA tworzą katalog z numerem
wersji, którego ezdxf domyślnie nie zna) i czytelne komunikaty.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
from collections.abc import Iterable
from pathlib import Path

import ezdxf

DWG_VERSIONS = ("R2000", "R2004", "R2007", "R2010", "R2013", "R2018")
ODA_URL = "https://www.opendesign.com/guestfiles/oda_file_converter"
ENV_VAR = "PDF2DXF_ODA_PATH"
EXE_NAMES = ("ODAFileConverter.exe", "ODAFileConverter")


class DwgError(Exception):
    """Konwersja do DWG nie powiodła się (plik DXF pozostaje zapisany)."""


class ConverterNotFound(DwgError):
    """Nie znaleziono ODA File Converter."""

    def __init__(self) -> None:
        super().__init__(
            "nie znaleziono ODA File Converter — plik DXF został zapisany, ale DWG nie. "
            f"Pobierz i zainstaluj program ze strony {ODA_URL}, a jeśli jest w nietypowym "
            f"miejscu, wskaż plik ODAFileConverter opcją --oda-path albo zmienną "
            f"środowiskową {ENV_VAR}."
        )


def _version_key(path: Path) -> tuple[int, ...]:
    """Klucz sortowania katalogów typu ``ODAFileConverter 25.12.0`` (najnowszy na końcu)."""
    return tuple(int(n) for n in re.findall(r"\d+", path.parent.name)) or (0,)


def _default_search_roots() -> list[Path]:
    roots = []
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        value = os.environ.get(var)
        if value:
            roots.append(Path(value))
    roots.append(Path(r"C:\Program Files"))
    return list(dict.fromkeys(roots))


def _as_executable(path: Path) -> Path | None:
    """Plik programu albo katalog, w którym on leży."""
    if path.is_file():
        return path
    if path.is_dir():
        for name in EXE_NAMES:
            if (path / name).is_file():
                return path / name
    return None


def find_converter(
    explicit: str | os.PathLike[str] | None = None,
    *,
    search_roots: Iterable[Path] | None = None,
) -> Path | None:
    """Szuka ODA File Converter.

    Kolejność: ``explicit`` (``--oda-path``) → zmienna ``PDF2DXF_ODA_PATH`` →
    ``PATH`` → ``<Program Files>/ODA/ODAFileConverter*/`` (najnowsza wersja) →
    typowe miejsca na macOS/Linux → ścieżka skonfigurowana w ezdxf.
    Wskazanie jawne (opcja lub zmienna), które nie istnieje, kończy
    wyszukiwanie wynikiem ``None`` — żeby nie użyć po cichu innej instalacji.
    """
    for given in (explicit, os.environ.get(ENV_VAR)):
        if given:
            return _as_executable(Path(given).expanduser())
    for name in EXE_NAMES:
        found = shutil.which(name)
        if found:
            return Path(found)
    roots = list(search_roots) if search_roots is not None else _default_search_roots()
    candidates: list[Path] = []
    for root in roots:
        candidates.extend(p for p in root.glob("ODA/ODAFileConverter*/ODAFileConverter.exe")
                          if p.is_file())
    if candidates:
        return max(candidates, key=_version_key)
    for fixed in (
        Path("/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter"),
        Path("/usr/bin/ODAFileConverter"),
        Path("/usr/local/bin/ODAFileConverter"),
    ):
        if fixed.is_file():
            return fixed
    from ezdxf.addons import odafc

    configured = Path(odafc.get_win_exec_path() if platform.system() == "Windows"
                      else odafc.get_unix_exec_path() or "")
    return configured if str(configured) not in ("", ".") and configured.is_file() else None


def _configure_ezdxf(exe: Path) -> None:
    """Przekazuje ścieżkę programu do ``ezdxf.addons.odafc`` (tylko w tym procesie)."""
    key = "win_exec_path" if platform.system() == "Windows" else "unix_exec_path"
    ezdxf.options.set("odafc-addon", key, str(exe))


def dxf_to_dwg(
    dxf_path: str | os.PathLike[str],
    dwg_path: str | os.PathLike[str] | None = None,
    *,
    version: str = "R2018",
    converter: str | os.PathLike[str] | None = None,
) -> Path:
    """Konwertuje plik DXF do DWG (domyślnie obok, z rozszerzeniem ``.dwg``).

    Raises:
        ConverterNotFound: brak ODA File Converter.
        DwgError: konwersja się nie powiodła.
    """
    from ezdxf.addons import odafc

    src = Path(dxf_path)
    dest = Path(dwg_path) if dwg_path is not None else src.with_suffix(".dwg")
    if version not in DWG_VERSIONS:
        raise DwgError(f"nieobsługiwana wersja DWG: {version}")
    exe = find_converter(converter)
    if exe is None:
        raise ConverterNotFound()
    _configure_ezdxf(exe)
    if dest.exists():
        dest.unlink()
    try:
        odafc.convert(src, dest, version=version, audit=True, replace=True)
    except odafc.ODAFCNotInstalledError as exc:
        raise ConverterNotFound() from exc
    except (odafc.ODAFCError, OSError) as exc:
        raise DwgError(f"konwersja {src.name} do DWG nie powiodła się: {exc}") from exc
    # ezdxf 1.4.5 nie zgłasza błędu, gdy ODA nie utworzy pliku — sprawdzamy sami
    if not dest.is_file() or dest.stat().st_size == 0:
        raise DwgError(f"ODA File Converter nie utworzył pliku {dest.name}")
    return dest
