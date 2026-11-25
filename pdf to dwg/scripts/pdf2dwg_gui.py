"""Punkt wejścia aplikacji okienkowej (dla PyInstaller).

Aplikacja okienkowa nie ma konsoli, więc błąd przy starcie zapisywany jest do
``%TEMP%\\PDF2DWG-blad.txt`` i pokazywany w okienku komunikatu.
"""

import sys
import tempfile
import traceback
from pathlib import Path


def _fatal(text: str) -> None:
    log = Path(tempfile.gettempdir()) / "PDF2DWG-blad.txt"
    try:
        log.write_text(text, encoding="utf-8")
    except OSError:
        pass
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None, f"PDF2DWG nie mógł się uruchomić.\n\nSzczegóły: {log}\n\n{text[-800:]}",
            "PDF2DWG — błąd", 0x10)


try:
    from pdf2dxf.gui import main

    code = main()
except Exception:
    _fatal(traceback.format_exc())
    code = 1
raise SystemExit(code)
