"""Aplikacja WWW: strona z formularzem i API zadań konwersji.

Uruchomienie lokalne::

    uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import (FileResponse, HTMLResponse, JSONResponse, PlainTextResponse,
                                 Response)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.jobs import Job, JobManager, QueueFull
from app.options import OptionsError, parse_options, safe_stem
from app.page import render_index
from app.settings import Settings

log = logging.getLogger("pdf2dwg")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
CHUNK = 1024 * 1024
FORM_OVERHEAD = 64 * 1024
"""Zapas na pola formularza i nagłówki multipart ponad rozmiar samego pliku."""

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    (b"content-security-policy",
     b"default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
     b"connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
]


class BodyTooLarge(Exception):
    pass


class LimitsMiddleware:
    """Nagłówki bezpieczeństwa + limit rozmiaru treści żądania (także bez Content-Length)."""

    def __init__(self, app: ASGIApp, max_body: int) -> None:
        self.app = app
        self.max_body = max_body

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + SECURITY_HEADERS
            await send(message)

        length = dict(scope["headers"]).get(b"content-length")
        if length is not None and length.isdigit() and int(length) > self.max_body:
            response = _error(413, "plik jest za duży")
            await response(scope, receive, send_with_headers)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body:
                    raise BodyTooLarge
            return message

        await self.app(scope, limited_receive, send_with_headers)


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _manager(request: Request) -> JobManager:
    return request.app.state.manager


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _job(request: Request) -> Job | None:
    return _manager(request).jobs.get(request.path_params["job_id"])


def _client(request: Request) -> str:
    return request.client.host if request.client else "?"


# --- strony ---------------------------------------------------------------------------

async def index(request: Request) -> Response:
    return HTMLResponse(request.app.state.index_html, headers={"cache-control": "no-cache"})


async def robots(request: Request) -> Response:
    return PlainTextResponse("User-agent: *\nAllow: /\nDisallow: /api/\n")


async def healthz(request: Request) -> Response:
    manager = _manager(request)
    running = sum(1 for j in manager.jobs.values() if j.status == "running")
    return JSONResponse({"ok": True, "queued": len(manager.pending), "running": running})


async def info(request: Request) -> Response:
    s = _settings(request)
    return JSONResponse({
        "dwg_available": s.dwg_available,
        "dwg_versions": list(s.dwg_versions),
        "max_upload_mb": s.max_upload_mb,
        "max_pages": s.max_pages,
        "retention_minutes": s.retention_minutes,
        "source_url": s.source_url,
        "contact": s.contact,
    })


# --- API zadań -----------------------------------------------------------------------

async def create_job(request: Request) -> Response:
    s = _settings(request)
    manager = _manager(request)
    client = _client(request)
    try:
        manager.check_capacity(client)
    except QueueFull as exc:
        return _error(429, str(exc))
    try:
        form = await request.form(max_files=1, max_fields=40)
    except BodyTooLarge:
        return _error(413, f"plik jest za duży (limit {s.max_upload_mb} MB)")
    except Exception as exc:  # uszkodzony multipart
        log.info("niepoprawny formularz: %s", exc)
        return _error(400, "niepoprawne żądanie")
    try:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            return _error(400, "nie przesłano pliku")
        try:
            options = parse_options(form, max_pages=s.max_pages, dwg_versions=s.dwg_versions,
                                    dwg_available=s.dwg_available)
        except OptionsError as exc:
            return _error(400, str(exc))
        job = manager.new_job(safe_stem(upload.filename), client)
        try:
            size = await _store_upload(upload, job.dir / "input.pdf", s.max_upload_bytes)
        except ValueError as exc:
            manager.discard(job)
            return _error(400 if "PDF" in str(exc) else 413, str(exc))
    finally:
        await form.close()
    await manager.submit(job, options)
    log.info("zadanie %s: %s (%.1f MB) od %s", job.id, job.stem, size / 1e6, client)
    return JSONResponse({"id": job.id}, status_code=202)


async def _store_upload(upload: UploadFile, dest: Path, limit: int) -> int:
    """Zapisuje plik, sprawdzając rozmiar i sygnaturę ``%PDF``. Zwraca rozmiar."""
    size = 0
    with dest.open("wb") as out:
        while chunk := await upload.read(CHUNK):
            if size == 0 and b"%PDF" not in chunk[:1024]:
                raise ValueError("to nie jest plik PDF")
            size += len(chunk)
            if size > limit:
                raise ValueError(f"plik jest za duży (limit {limit // (1024 * 1024)} MB)")
            out.write(chunk)
    if size == 0:
        raise ValueError("plik jest pusty — to nie jest plik PDF")
    return size


def _public_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    public = {k: v for k, v in result.items() if k != "download"}
    if "download" in result:
        public["download"] = {k: v for k, v in result["download"].items() if k != "path"}
    return public


async def job_status(request: Request) -> Response:
    job = _job(request)
    if job is None:
        return _error(404, "nie ma takiego zadania (pliki są kasowane po zakończeniu)")
    manager = _manager(request)
    return JSONResponse({
        "id": job.id,
        "status": job.status,
        "position": manager.position(job),
        "error": job.error,
        "result": _public_result(job.result),
        "preview": (job.dir / "preview.png").is_file(),
        "expires_in": (None if job.finished is None else max(
            0, int(job.finished + _settings(request).retention_minutes * 60 - time.time()))),
    }, headers={"cache-control": "no-store"})


async def job_download(request: Request) -> Response:
    job = _job(request)
    if job is None or job.status != "done" or not job.result:
        return _error(404, "plik nie jest dostępny")
    download = job.result["download"]
    path = job.dir / download["path"]
    if not path.is_file():
        return _error(404, "plik nie jest dostępny")
    return FileResponse(path, filename=download["name"], media_type=_media_type(path),
                        headers={"cache-control": "no-store"})


async def job_file(request: Request) -> Response:
    job = _job(request)
    name = request.path_params["name"]
    if job is None or job.status != "done" or not job.result:
        return _error(404, "plik nie jest dostępny")
    if name not in {f["name"] for f in job.result.get("files", [])}:
        return _error(404, "plik nie jest dostępny")
    path = job.dir / "out" / name
    if not path.is_file():
        return _error(404, "plik nie jest dostępny")
    return FileResponse(path, filename=name, media_type=_media_type(path),
                        headers={"cache-control": "no-store"})


async def job_preview(request: Request) -> Response:
    job = _job(request)
    path = job.dir / "preview.png" if job else None
    if path is None or not path.is_file():
        return _error(404, "brak podglądu")
    return FileResponse(path, media_type="image/png", headers={"cache-control": "private"})


async def job_delete(request: Request) -> Response:
    job = _job(request)
    if job is not None:
        _manager(request).discard(job)
    return Response(status_code=204)


def _media_type(path: Path) -> str:
    return {".zip": "application/zip"}.get(path.suffix.lower(), "application/octet-stream")


# --- aplikacja -----------------------------------------------------------------------

def create_app(settings: Settings | None = None) -> ASGIApp:
    settings = settings or Settings.from_env()

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        manager = JobManager(settings)
        app.state.manager = manager
        app.state.settings = settings
        await manager.start()
        log.info("silnik DWG: %s, równoległe konwersje: %d, limit pliku: %d MB",
                 settings.dwg_engine, settings.workers, settings.max_upload_mb)
        if settings.dwg_engine == "oda":
            log.warning("ODA File Converter: darmowa licencja ODA zabrania użycia w usłudze dla "
                        "osób trzecich — używaj tylko lokalnie / wewnętrznie")
        try:
            yield
        finally:
            await manager.stop()

    routes = [
        Route("/", index),
        Route("/robots.txt", robots),
        Route("/healthz", healthz),
        Route("/api/info", info),
        Route("/api/jobs", create_job, methods=["POST"]),
        Route("/api/jobs/{job_id}", job_status),
        Route("/api/jobs/{job_id}", job_delete, methods=["DELETE"]),
        Route("/api/jobs/{job_id}/download", job_download),
        Route("/api/jobs/{job_id}/files/{name}", job_file),
        Route("/api/jobs/{job_id}/preview.png", job_preview),
        Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.index_html = render_index(settings)
    return LimitsMiddleware(app, settings.max_upload_bytes + FORM_OVERHEAD)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def __getattr__(name: str) -> Any:
    """``app.main:app`` tworzy aplikację dopiero przy pierwszym użyciu (testy jej nie potrzebują)."""
    if name == "app":
        value = create_app()
        globals()["app"] = value
        return value
    raise AttributeError(name)
