# syntax=docker/dockerfile:1.7
#
# Obraz strony PDF → DWG/DXF. Budowanie (z katalogu strony):
#   docker compose build
# Kod konwertera pochodzi z drugiego kontekstu "pdf2dxf" (katalog "../pdf to dwg"),
# kopiowane są tylko src/, pyproject.toml i README.md — bez .venv, próbek i dist/.
#
# Silnik DWG: domyślnie brak (strona oddaje DXF). ODA File Converter NIE jest tu
# instalowany celowo — jego darmowa licencja zabrania użycia w usłudze dla osób trzecich.

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PDF2DWG_DATA_DIR=/data

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --from=pdf2dxf pyproject.toml README.md /tmp/pdf2dxf/
COPY --from=pdf2dxf src /tmp/pdf2dxf/src
RUN pip install --no-deps /tmp/pdf2dxf && rm -rf /tmp/pdf2dxf

COPY app ./app
COPY static ./static

RUN useradd --system --uid 10001 --no-create-home web \
    && mkdir -p /data && chown web /data
USER web

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

# --proxy-headers: adres klienta z nagłówków Caddy (port 8000 nie jest wystawiany na zewnątrz)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
