"""Konfiguracja serwera — wartości ze zmiennych środowiskowych ``PDF2DWG_*``."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

DWG_ENGINES = ("none", "oda", "command")
DWG_VERSIONS = ("R2000", "R2004", "R2007", "R2010", "R2013", "R2018")


def _env(name: str, default: str) -> str:
    return os.environ.get(f"PDF2DWG_{name}", default).strip()


def _env_int(name: str, default: int) -> int:
    value = _env(name, str(default))
    try:
        return int(value)
    except ValueError:
        raise SystemExit(f"PDF2DWG_{name} musi być liczbą całkowitą, jest: {value!r}") from None


@dataclass(frozen=True)
class Settings:
    """Ustawienia serwera. Domyślne wartości są bezpieczne do publicznego użycia."""

    data_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()) / "pdf2dwg-web")
    max_upload_mb: int = 50
    """Największy przyjmowany plik PDF."""
    max_pages: int = 100
    """Najwięcej stron konwertowanych z jednego pliku."""
    job_timeout: int = 180
    """Limit czasu jednej konwersji (sekundy) — chroni serwer przed plikami-bombami."""
    job_memory_mb: int = 1500
    """Limit pamięci jednej konwersji (MB, 0 = bez limitu). Gęsty PDF potrafi zająć kilka GB
    (ok. 3,5 KB na odcinek) — po przekroczeniu proces jest zabijany."""
    workers: int = 2
    """Ile konwersji naraz."""
    max_queue: int = 50
    """Najwięcej zadań czekających w kolejce (powyżej — „serwer zajęty”)."""
    max_active_per_client: int = 6
    """Najwięcej niezakończonych zadań jednego adresu IP (uczciwy podział kolejki)."""
    retention_minutes: int = 30
    """Po tylu minutach od zakończenia pliki zadania są kasowane."""
    min_free_mb: int = 1024
    """Poniżej tylu MB wolnego miejsca w ``data_dir`` nowe pliki nie są przyjmowane."""
    dwg_engine: str = "none"
    """``none`` — tylko DXF; ``oda`` — ODA File Converter; ``command`` — własne polecenie."""
    dwg_command: str = ""
    """Szablon polecenia dla ``command``, np. ``dxf2dwg {input} {output} {version}``."""
    dwg_versions: tuple[str, ...] = DWG_VERSIONS
    oda_path: str | None = None
    source_url: str = ""
    """Adres kodu źródłowego (wymóg licencji AGPL PyMuPDF przy usłudze sieciowej)."""
    contact: str = ""

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def dwg_available(self) -> bool:
        return self.dwg_engine != "none"

    @classmethod
    def from_env(cls) -> Settings:
        engine = _env("DWG_ENGINE", "none").lower()
        if engine not in DWG_ENGINES:
            raise SystemExit(f"PDF2DWG_DWG_ENGINE: {engine!r} — dozwolone: {', '.join(DWG_ENGINES)}")
        command = _env("DWG_COMMAND", "")
        if engine == "command" and not command:
            raise SystemExit("PDF2DWG_DWG_ENGINE=command wymaga PDF2DWG_DWG_COMMAND")
        versions = tuple(v.strip().upper() for v in _env("DWG_VERSIONS", ",".join(DWG_VERSIONS))
                         .split(",") if v.strip())
        bad = [v for v in versions if v not in DWG_VERSIONS]
        if bad or not versions:
            raise SystemExit(f"PDF2DWG_DWG_VERSIONS: nieznane wersje {bad}")
        data_dir = _env("DATA_DIR", "")
        return cls(
            data_dir=Path(data_dir) if data_dir else cls().data_dir,
            max_upload_mb=_env_int("MAX_UPLOAD_MB", cls.max_upload_mb),
            max_pages=_env_int("MAX_PAGES", cls.max_pages),
            job_timeout=_env_int("JOB_TIMEOUT", cls.job_timeout),
            job_memory_mb=max(0, _env_int("JOB_MEMORY_MB", cls.job_memory_mb)),
            workers=max(1, _env_int("WORKERS", cls.workers)),
            max_queue=_env_int("MAX_QUEUE", cls.max_queue),
            max_active_per_client=_env_int("MAX_ACTIVE_PER_CLIENT", cls.max_active_per_client),
            retention_minutes=_env_int("RETENTION_MINUTES", cls.retention_minutes),
            min_free_mb=_env_int("MIN_FREE_MB", cls.min_free_mb),
            dwg_engine=engine,
            dwg_command=command,
            dwg_versions=versions,
            oda_path=_env("ODA_PATH", "") or None,
            source_url=_env("SOURCE_URL", ""),
            contact=_env("CONTACT", ""),
        )
