"""Walidacja opcji konwersji przesłanych z formularza strony."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

UNITS = ("mm", "cm", "m", "in")
CURVES = ("spline", "polyline")
LAYERS = ("by-color", "by-ocg", "single")
FILLS = ("hatch", "outline", "ignore")
FORMATS = ("dwg", "dxf")
MAX_SCALE = 100_000.0

_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                     *(f"LPT{i}" for i in range(1, 10))}


class OptionsError(ValueError):
    """Niepoprawna wartość opcji — komunikat jest pokazywany użytkownikowi."""


def parse_scale(text: str) -> float:
    """``50``, ``1:50``, ``1/50`` → 50.0."""
    text = text.strip().replace(" ", "").replace(",", ".")
    if not text:
        return 1.0
    match = re.fullmatch(r"(?:1[:/])?(\d+(?:\.\d+)?)", text)
    if not match:
        raise OptionsError(f"niepoprawna skala: {text!r} (wpisz np. 50 albo 1:50)")
    value = float(match.group(1))
    if not 0 < value <= MAX_SCALE:
        raise OptionsError(f"skala poza zakresem: {text!r}")
    return value


def parse_pages(text: str, max_pages: int) -> list[int] | None:
    """``"1,3-5"`` → [1, 3, 4, 5]; pusty napis → None (wszystkie strony).

    Zakres jest ograniczony z góry, żeby zapis typu ``1-999999999`` nie zajął pamięci.
    """
    text = text.strip()
    if not text:
        return None
    pages: set[int] = set()
    upper = 10_000
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not match:
            raise OptionsError(f"niepoprawny zakres stron: {part!r} (wpisz np. 1,3-5)")
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start < 1 or end < start:
            raise OptionsError(f"niepoprawny zakres stron: {part!r}")
        if end > upper:
            raise OptionsError(f"za duży numer strony: {end}")
        pages.update(range(start, end + 1))
        if len(pages) > max_pages:
            raise OptionsError(f"można wybrać najwyżej {max_pages} stron naraz")
    if not pages:
        return None
    return sorted(pages)


def _choice(form: Mapping[str, Any], name: str, allowed: tuple[str, ...], default: str) -> str:
    value = str(form.get(name, default) or default).strip().lower()
    if value not in allowed:
        raise OptionsError(f"niepoprawna wartość {name}: {value!r}")
    return value


def _flag(form: Mapping[str, Any], name: str, default: bool) -> bool:
    value = form.get(name)
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "on", "yes", "tak")


def parse_options(
    form: Mapping[str, Any], *, max_pages: int, dwg_versions: tuple[str, ...], dwg_available: bool
) -> dict[str, Any]:
    """Zamienia pola formularza na słownik ``{"convert": {...}, "format": ..., "dwg_version": ...}``.

    ``convert`` ma klucze zgodne z :class:`pdf2dxf.converter.ConvertOptions`.
    """
    fmt = _choice(form, "format", FORMATS, "dwg" if dwg_available else "dxf")
    if fmt == "dwg" and not dwg_available:
        raise OptionsError("zapis DWG jest chwilowo niedostępny — wybierz DXF")
    dwg_version = str(form.get("dwg_version") or dwg_versions[-1]).strip().upper()
    if dwg_version not in dwg_versions:
        raise OptionsError(f"nieobsługiwana wersja DWG: {dwg_version!r}")
    convert = {
        "pages": parse_pages(str(form.get("pages", "")), max_pages),
        "single_file": _flag(form, "single_file", False),
        "units": _choice(form, "units", UNITS, "mm"),
        "scale": parse_scale(str(form.get("scale", ""))),
        "curves": _choice(form, "curves", CURVES, "spline"),
        "detect_arcs": _flag(form, "detect_arcs", True),
        "join": _flag(form, "join", False),
        "layers": _choice(form, "layers", LAYERS, "by-color"),
        "fills": _choice(form, "fills", FILLS, "hatch"),
        "text": _flag(form, "text", True),
        "merge_text": _flag(form, "merge_text", False),
    }
    return {"convert": convert, "format": fmt, "dwg_version": dwg_version}


def safe_stem(filename: str | None) -> str:
    """Bezpieczny rdzeń nazwy pliku wynikowego z nazwy przesłanego PDF (polskie litery zostają)."""
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    name = unicodedata.normalize("NFC", name)
    cleaned = "".join(ch if (ch.isalnum() or ch in " -_.,()[]#+&") else "_" for ch in name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._")[:80].rstrip(" ._")
    if not cleaned:
        return "rysunek"
    if cleaned.split(".")[0].upper() in _WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned
