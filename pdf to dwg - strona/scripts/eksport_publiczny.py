"""Eksport czystej kopii kodu do publicznego repozytorium (wymóg licencji AGPL).

Kopiuje WYŁĄCZNIE pliki z listy dozwolonych — nigdy próbek (``samples``), wyników
konwersji, środowisk (``.venv``), plików ``.env`` ani ustawień lokalnych. Jeśli w
zestawie znajdzie się plik o zabronionym rozszerzeniu (PDF, DXF, DWG, ZIP, EXE,
obraz), eksport przerywa się, zanim cokolwiek skopiuje.

Repozytorium ma dwa katalogi o tych samych nazwach co lokalnie, więc
``docker-compose.yml`` (``../pdf to dwg``) działa w nim bez zmian::

    pdf2dwg/
      README.md, LICENSE, .gitignore      ← utrzymywane w repozytorium, skrypt ich nie rusza
      pdf to dwg/                          ← konwerter
      pdf to dwg - strona/                 ← strona WWW

Użycie (z katalogu strony)::

    python scripts/eksport_publiczny.py [KATALOG_REPOZYTORIUM]

Domyślny katalog: ``pdf2dwg`` obok obu katalogów projektu. Po eksporcie: przejrzyj
``git status`` i ``git diff``, potem commit i push.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent
CONVERTER = WEB.parent / "pdf to dwg"

INCLUDE: dict[Path, list[str]] = {
    CONVERTER: [".gitattributes", ".gitignore", "pyproject.toml", "README.md", "DOKUMENTACJA.md",
                "SPEC.md", "src", "tests", "scripts"],
    WEB: [".gitignore", ".dockerignore", ".env.example", "requirements.txt",
          "requirements-dev.txt", "Dockerfile", "docker-compose.yml", "Caddyfile",
          "WDROZENIE.md", "app", "static", "tests", "scripts"],
}
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".venv", ".git", ".claude", "samples", "build",
             "dist", "out"}
FORBIDDEN_SUFFIXES = {".pdf", ".dxf", ".dwg", ".dwf", ".zip", ".7z", ".exe", ".dll", ".pyc",
                      ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".log"}
FORBIDDEN_NAMES = {".env", "launch.json", "settings.local.json"}
MARKER = ".eksport-publiczny"
"""Plik-znacznik: eksport kasuje i odtwarza podkatalogi tylko w katalogu, który go ma."""


def collect(root: Path, items: list[str]) -> list[Path]:
    files: list[Path] = []
    for item in items:
        path = root / item
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(p for p in sorted(path.rglob("*")) if p.is_file() and not any(
                part in SKIP_DIRS or part.endswith(".egg-info")
                for part in p.relative_to(root).parts))
        else:
            raise SystemExit(f"brak pliku z listy dozwolonych: {path}")
    return files


def main(argv: list[str]) -> int:
    dest = (Path(argv[1]) if len(argv) > 1 else WEB.parent / "pdf2dwg").resolve()
    if dest in (WEB, CONVERTER, WEB.parent) or WEB.is_relative_to(dest) \
            or CONVERTER.is_relative_to(dest) or dest.is_relative_to(WEB) \
            or dest.is_relative_to(CONVERTER):
        raise SystemExit(f"katalog docelowy nie może zawierać projektu ani być w nim: {dest}")
    if dest.exists() and any(dest.iterdir()) and not (dest / MARKER).is_file():
        raise SystemExit(f"{dest} nie jest pusty i nie ma znacznika {MARKER} — "
                         f"wybierz pusty katalog albo katalog poprzedniego eksportu")

    plan = {root: collect(root, items) for root, items in INCLUDE.items()}
    bad = [p for files in plan.values() for p in files
           if p.suffix.lower() in FORBIDDEN_SUFFIXES or p.name in FORBIDDEN_NAMES]
    if bad:
        listing = "\n  ".join(str(p) for p in bad)
        raise SystemExit(f"eksport przerwany — pliki, których nie wolno publikować:\n  {listing}")

    dest.mkdir(parents=True, exist_ok=True)
    (dest / MARKER).write_text("katalog eksportu: scripts/eksport_publiczny.py\n", encoding="utf-8")
    for root, files in plan.items():
        target = dest / root.name
        if target.exists():
            shutil.rmtree(target)
        for src in files:
            out = target / src.relative_to(root)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)
        size = sum(p.stat().st_size for p in files)
        print(f"{root.name}: {len(files)} plików, {size / 1024:.0f} KB")
    print(f"gotowe: {dest}\nteraz: git status, git diff, potem commit i push")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
