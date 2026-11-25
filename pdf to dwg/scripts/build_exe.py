"""Buduje jednoplikową aplikację Windows ``dist/PDF2DWG.exe`` (PyInstaller).

Użycie (w środowisku z ``pip install -e ".[build]"``)::

    python scripts/build_exe.py

Aplikacja zawiera Pythona i wszystkie biblioteki; do zapisu DWG potrzebny
jest zainstalowany osobno ODA File Converter.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
NAME = "PDF2DWG"
EXCLUDES = [  # uwaga: nie wykluczać "unittest" — importuje go pyparsing (zależność ezdxf)
    "matplotlib", "PIL", "pytest", "_pytest", "pymupdf_fonts", "IPython",
    "scipy", "pandas", "tkinter.test", "pydoc_data",
]


def make_icon(path: Path) -> Path | None:
    """Prosta ikona „PDF → DWG” (wymaga Pillow; bez niego domyślna ikona)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, size - 8, size - 8), radius=40, fill=(29, 78, 216))
    try:
        font = ImageFont.truetype("arialbd.ttf", 74)
        small = ImageFont.truetype("arialbd.ttf", 54)
    except OSError:
        font = small = ImageFont.load_default()
    d.text((size / 2, 78), "PDF", font=font, fill="white", anchor="mm")
    d.text((size / 2, 132), "↓", font=small, fill=(191, 219, 254), anchor="mm")
    d.text((size / 2, 188), "DWG", font=font, fill="white", anchor="mm")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return path


def main() -> int:
    import PyInstaller.__main__

    console = "--console" in sys.argv  # wariant diagnostyczny: okno konsoli z błędami
    name = f"{NAME}-console" if console else NAME
    icon = make_icon(BUILD / f"{NAME}.ico")
    args = [
        str(ROOT / "scripts" / "pdf2dwg_gui.py"),
        "--name", name,
        "--onefile",
        "--console" if console else "--windowed",
        "--noconfirm",
        "--clean",
        "--paths", str(ROOT / "src"),
        "--collect-all", "tkinterdnd2",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(BUILD / "pyinstaller"),
        "--specpath", str(BUILD),
    ]
    for module in EXCLUDES:
        args += ["--exclude-module", module]
    if icon is not None:
        args += ["--icon", str(icon)]
    PyInstaller.__main__.run(args)
    exe = ROOT / "dist" / f"{name}.exe"
    print(f"\nGotowe: {exe} ({exe.stat().st_size / 1e6:.1f} MB)" if exe.exists() else "Błąd budowania")
    return 0 if exe.exists() else 1


if __name__ == "__main__":
    sys.exit(main())
