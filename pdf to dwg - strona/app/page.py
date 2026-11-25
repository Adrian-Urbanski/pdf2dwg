"""Strona główna: szablon ``templates/index.html`` z tekstami zależnymi od trybu.

Gdy serwer nie ma silnika DWG (``PDF2DWG_DWG_ENGINE=none``), strona mówi uczciwie
o DXF — tytuł, nagłówek, kroki i FAQ — i ukrywa wybór formatu. Po podłączeniu
legalnego silnika DWG teksty same wracają do DWG.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.settings import Settings

TEMPLATE = Path(__file__).resolve().parent / "templates" / "index.html"

TEXTS: dict[str, dict[str, str]] = {
    "dwg": {
        "title": "Konwerter PDF do DWG — za darmo, bez limitu",
        "description": "Darmowy konwerter PDF do DWG i DXF bez limitu plików i bez rejestracji. "
                       "Wektorowe rysunki PDF zamienione na linie, łuki, okręgi, tekst i warstwy "
                       "dla AutoCAD, BricsCAD i ZWCAD.",
        "og_description": "Wektorowy PDF → DWG/DXF. Bez limitu, bez rejestracji, bez znaku wodnego.",
        "h1": "Konwerter PDF do DWG",
        "lead": "Zamień wektorowy rysunek PDF na plik DWG albo DXF — z liniami, łukami, okręgami, "
                "tekstem i warstwami. Za darmo i bez limitu.",
        "target": "DWG",
        "formats": "DWG/DXF",
        "faq_format_q": "DWG czy DXF?",
        "faq_format_a": "DWG to natywny format AutoCAD. DXF to otwarty format wymiany, który "
                        "otworzy każdy program CAD (także LibreCAD, QCAD, Fusion 360, programy "
                        "CNC) — zawartość jest taka sama.",
    },
    "dxf": {
        "title": "Konwerter PDF do DXF dla AutoCAD — za darmo, bez limitu",
        "description": "Darmowy konwerter PDF do DXF bez limitu plików i bez rejestracji. "
                       "Wektorowe rysunki PDF zamienione na linie, łuki, okręgi, tekst i warstwy "
                       "— otworzysz je w AutoCAD, BricsCAD i ZWCAD i zapiszesz jako DWG.",
        "og_description": "Wektorowy PDF → DXF dla AutoCAD. Bez limitu, bez rejestracji, "
                          "bez znaku wodnego.",
        "h1": "Konwerter PDF do DXF",
        "lead": "Zamień wektorowy rysunek PDF na plik DXF — z liniami, łukami, okręgami, tekstem "
                "i warstwami. Otworzysz go w AutoCAD tak jak DWG. Za darmo i bez limitu.",
        "target": "DXF",
        "formats": "DXF",
        "faq_format_q": "Dlaczego DXF, a nie DWG?",
        "faq_format_a": "DXF to otwarty format wymiany rysunków AutoCAD — zawartość jest taka "
                        "sama jak w DWG. Otworzysz go w AutoCAD, BricsCAD, ZWCAD i DraftSight, "
                        "a także w LibreCAD, QCAD, Fusion 360 i programach CNC. Potrzebujesz DWG? "
                        "Otwórz plik w AutoCAD i wybierz „Zapisz jako” → DWG.",
    },
}

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def render_index(settings: Settings) -> str:
    """Zwraca gotowy HTML strony głównej (nieznany znacznik → KeyError, a nie pusty tekst)."""
    mode = "dwg" if settings.dwg_available else "dxf"
    values = TEXTS[mode] | {
        "mode": mode,
        "max_mb": str(settings.max_upload_mb),
        "max_pages": str(settings.max_pages),
        "retention": str(settings.retention_minutes),
    }
    template = TEMPLATE.read_text(encoding="utf-8")
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], template)
