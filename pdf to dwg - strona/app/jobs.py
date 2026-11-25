"""Kolejka zadań konwersji: przyjmowanie, uruchamianie w osobnych procesach, sprzątanie."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.settings import Settings

log = logging.getLogger("pdf2dwg.jobs")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLEANUP_INTERVAL = 60
POLL_INTERVAL = 0.25
"""Co ile sekund sprawdzany jest czas i pamięć procesu konwersji."""


class QueueFull(Exception):
    """Serwer nie przyjmie teraz zadania — komunikat dla użytkownika."""


@dataclass
class Job:
    id: str
    dir: Path
    stem: str
    client: str
    status: str = "queued"  # queued → running → done | error
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    @property
    def active(self) -> bool:
        return self.status in ("queued", "running")


def kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """Zabija proces razem z procesami potomnymi (np. ODA File Converter, Xvfb)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, check=False)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class _MemoryCounters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                "PagefileUsage", "PeakPagefileUsage")
        ]

    class _ProcessEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

    _k32 = ctypes.WinDLL("kernel32")
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MemoryCounters),
                                             wintypes.DWORD]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
    _k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]

    def _windows_private_mb(pid: int) -> float:
        handle = _k32.OpenProcess(0x1000 | 0x0010, False, pid)  # QUERY_LIMITED_INFORMATION | VM_READ
        if not handle:
            return 0.0
        try:
            counters = _MemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            if not _k32.K32GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return 0.0
            return counters.PagefileUsage / 2**20
        finally:
            _k32.CloseHandle(handle)

    def _windows_tree_memory_mb(root: int) -> float | None:
        snapshot = _k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if not snapshot or snapshot == ctypes.c_void_p(-1).value:
            return None
        parents: dict[int, int] = {}
        try:
            entry = _ProcessEntry()
            entry.dwSize = ctypes.sizeof(entry)
            ok = _k32.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                parents[entry.th32ProcessID] = entry.th32ParentProcessID
                ok = _k32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            _k32.CloseHandle(snapshot)
        tree, frontier = {root}, [root]
        while frontier:
            parent = frontier.pop()
            for pid, ppid in parents.items():
                if ppid == parent and pid not in tree:
                    tree.add(pid)
                    frontier.append(pid)
        return sum(_windows_private_mb(pid) for pid in tree)


def _linux_group_memory_mb(pgid: int) -> float | None:
    """Suma RSS + swap procesów z grupy ``pgid`` (proces konwersji i jego potomne)."""
    total_kb, found = 0, False
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        try:
            with open(f"/proc/{entry.name}/stat", "rb") as fh:
                stat = fh.read()
            # "pid (nazwa) stan ppid pgrp ..." — nazwa może zawierać spacje i nawiasy
            if int(stat[stat.rindex(b")") + 2:].split()[2]) != pgid:
                continue
            with open(f"/proc/{entry.name}/status", encoding="ascii", errors="replace") as fh:
                for line in fh:
                    if line.startswith(("VmRSS:", "VmSwap:")):
                        total_kb += int(line.split()[1])
            found = True
        except (OSError, ValueError, IndexError):
            continue
    return total_kb / 1024 if found else None


def process_tree_memory_mb(pid: int) -> float | None:
    """Pamięć procesu ``pid`` razem z potomnymi, w MB; None — nie da się zmierzyć.

    Linux: RSS + swap grupy procesów (proces konwersji startuje we własnej sesji).
    Windows: pamięć prywatna drzewa procesów (``python.exe`` z venv to tylko launcher,
    właściwy interpreter jest jego dzieckiem).
    """
    if sys.platform.startswith("linux"):
        return _linux_group_memory_mb(pid)
    if os.name == "nt":
        return _windows_tree_memory_mb(pid)
    return None


def _tail(path: Path, limit: int = 8000) -> str:
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - limit))
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def run_worker(job_dir: Path, timeout: float, memory_mb: int = 0) -> tuple[str, str]:
    """Uruchamia ``app.worker`` dla zadania i pilnuje limitów czasu i pamięci.

    Zwraca (wynik, końcówkę wyjścia diagnostycznego); wynik to ``finished``, ``timeout``
    albo ``memory`` — w dwóch ostatnich przypadkach proces został zabity razem z potomnymi.
    Wyjście idzie do pliku (nie do potoku), żeby pętla mogła co chwilę sprawdzać proces.
    """
    log_path = job_dir / "worker.log"
    with log_path.open("wb") as log_file:
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.worker", str(job_dir)],
            cwd=PROJECT_ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    deadline = time.monotonic() + timeout
    outcome = "finished"
    while True:
        try:
            proc.wait(timeout=POLL_INTERVAL)
            break
        except subprocess.TimeoutExpired:
            pass
        if time.monotonic() > deadline:
            outcome = "timeout"
        elif memory_mb and (used := process_tree_memory_mb(proc.pid)) is not None and used > memory_mb:
            outcome = "memory"
        else:
            continue
        kill_tree(proc)
        proc.wait()
        break
    output = _tail(log_path)
    log_path.unlink(missing_ok=True)
    return outcome, output


class JobManager:
    """Przechowuje zadania w pamięci, a ich pliki w ``settings.data_dir``."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.jobs: dict[str, Job] = {}
        self.pending: deque[str] = deque()
        self._wakeup: asyncio.Condition | None = None
        self._tasks: list[asyncio.Task[None]] = []

    # --- cykl życia -----------------------------------------------------------------

    async def start(self) -> None:
        root = self.settings.data_dir
        if root.exists():  # pozostałości po poprzednim uruchomieniu
            shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        self._wakeup = asyncio.Condition()
        for n in range(self.settings.workers):
            self._tasks.append(asyncio.create_task(self._worker_loop(), name=f"worker-{n}"))
        self._tasks.append(asyncio.create_task(self._cleanup_loop(), name="cleanup"))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    # --- przyjmowanie ----------------------------------------------------------------

    def check_capacity(self, client: str) -> None:
        if len(self.pending) >= self.settings.max_queue:
            raise QueueFull("serwer jest teraz mocno obciążony — spróbuj ponownie za minutę")
        free_mb = shutil.disk_usage(self.settings.data_dir).free // (1024 * 1024)
        if free_mb < self.settings.min_free_mb:
            log.warning("mało miejsca na dysku: %d MB", free_mb)
            raise QueueFull("serwer jest teraz mocno obciążony — spróbuj ponownie za kilka minut")
        active = sum(1 for j in self.jobs.values() if j.client == client and j.active)
        if active >= self.settings.max_active_per_client:
            raise QueueFull(
                f"masz już {active} plików w trakcie konwersji — poczekaj, aż się skończą"
            )

    def new_job(self, stem: str, client: str) -> Job:
        job_id = secrets.token_urlsafe(18)
        job_dir = self.settings.data_dir / job_id
        job_dir.mkdir(parents=True)
        return Job(id=job_id, dir=job_dir, stem=stem, client=client)

    async def submit(self, job: Job, options: dict[str, Any]) -> None:
        """Zapisuje ``job.json`` i wstawia zadanie do kolejki (plik ``input.pdf`` już jest)."""
        s = self.settings
        spec = {
            "stem": job.stem,
            "options": options,
            "max_pages": s.max_pages,
            "engine": {"name": s.dwg_engine, "command": s.dwg_command, "oda_path": s.oda_path},
        }
        (job.dir / "job.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        self.jobs[job.id] = job
        self.pending.append(job.id)
        assert self._wakeup is not None
        async with self._wakeup:
            self._wakeup.notify()

    def discard(self, job: Job) -> None:
        """Usuwa zadanie i jego pliki (także w trakcie kolejki)."""
        self.jobs.pop(job.id, None)
        try:
            self.pending.remove(job.id)
        except ValueError:
            pass
        if job.status != "running":  # katalog uruchomionego zadania usunie wątek po zakończeniu
            shutil.rmtree(job.dir, ignore_errors=True)

    def position(self, job: Job) -> int | None:
        try:
            return self.pending.index(job.id) + 1
        except ValueError:
            return None

    # --- wykonanie -------------------------------------------------------------------

    async def _worker_loop(self) -> None:
        assert self._wakeup is not None
        while True:
            async with self._wakeup:
                await self._wakeup.wait_for(lambda: bool(self.pending))
                job_id = self.pending.popleft()
            job = self.jobs.get(job_id)
            if job is None:
                continue
            await self._run(job)

    async def _run(self, job: Job) -> None:
        job.status = "running"
        job.started = time.time()
        try:
            s = self.settings
            outcome, output = await asyncio.to_thread(
                run_worker, job.dir, s.job_timeout, s.job_memory_mb
            )
            if output.strip():
                log.info("zadanie %s:\n%s", job.id, output.strip()[-4000:])
            if outcome == "timeout":
                job.error = (f"konwersja trwała dłużej niż {s.job_timeout} s i została "
                             f"przerwana — spróbuj z mniejszą liczbą stron")
            elif outcome == "memory":
                log.warning("zadanie %s: przekroczony limit pamięci %d MB", job.id, s.job_memory_mb)
                job.error = ("plik jest zbyt złożony — konwersja przekroczyła limit pamięci serwera "
                             "i została przerwana; spróbuj z mniejszą liczbą stron")
            else:
                result_file = job.dir / "result.json"
                if result_file.is_file():
                    job.result = json.loads(result_file.read_text(encoding="utf-8"))
                    if not job.result.get("ok"):
                        job.error = job.result.get("error") or "konwersja nie powiodła się"
                else:
                    job.error = "konwersja przerwana (plik zbyt złożony albo uszkodzony)"
        except Exception:
            log.exception("zadanie %s: błąd uruchomienia", job.id)
            job.error = "błąd serwera podczas konwersji"
        job.status = "error" if job.error else "done"
        job.finished = time.time()
        # oryginał nie jest już potrzebny (ponowna konwersja wysyła plik jeszcze raz)
        (job.dir / "input.pdf").unlink(missing_ok=True)
        if job.id not in self.jobs:  # usunięte przez użytkownika w trakcie
            shutil.rmtree(job.dir, ignore_errors=True)
        log.info("zadanie %s: %s w %.1f s", job.id, job.status, job.finished - job.started)

    # --- sprzątanie ------------------------------------------------------------------

    def cleanup(self, now: float | None = None) -> int:
        """Kasuje zadania zakończone dawniej niż ``retention_minutes``. Zwraca ich liczbę."""
        now = time.time() if now is None else now
        limit = self.settings.retention_minutes * 60
        expired = [j for j in self.jobs.values()
                   if not j.active and j.finished is not None and now - j.finished > limit]
        for job in expired:
            self.discard(job)
        return len(expired)

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL)
            try:
                removed = self.cleanup()
                if removed:
                    log.info("usunięto %d starych zadań", removed)
            except Exception:
                log.exception("sprzątanie nie powiodło się")
