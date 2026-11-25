"""Atrapa konwertera DXF → DWG do testów: ``fake_dwg.py WEJŚCIE WYJŚCIE WERSJA``."""

import sys
import time
from pathlib import Path

src, dest, version = sys.argv[1:4]
if version == "FAIL":
    print("atrapa: błąd konwersji", file=sys.stderr)
    sys.exit(1)
if version == "SLEEP":
    time.sleep(30)
Path(dest).write_bytes(f"FAKE {version}\n".encode() + Path(src).read_bytes()[:100])
