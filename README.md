# PDF2DWG

Darmowy konwerter **wektorowych** rysunków PDF do DXF (i DWG) — z liniami, łukami,
okręgami, krzywymi, wypełnieniami, tekstem i warstwami. Bez limitu plików, bez
rejestracji, bez znaku wodnego.

| Katalog | Co zawiera |
|---|---|
| [`pdf to dwg/`](pdf%20to%20dwg/) | konwerter: pakiet Python `pdf2dxf`, wiersz poleceń i program okienkowy PDF2DWG — opis w [README](pdf%20to%20dwg/README.md), szczegóły w [DOKUMENTACJA](pdf%20to%20dwg/DOKUMENTACJA.md) |
| [`pdf to dwg - strona/`](pdf%20to%20dwg%20-%20strona/) | strona WWW: serwer, kolejka konwersji, Docker + Caddy — uruchomienie, wdrożenie i bezpieczeństwo w [WDROZENIE](pdf%20to%20dwg%20-%20strona/WDROZENIE.md) |

## Strona lokalnie (Windows)

```powershell
cd "pdf to dwg - strona"
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e "..\pdf to dwg" -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8765
```

Strona: <http://localhost:8765>. Na serwer: `docker compose up -d --build` w katalogu
strony (szczegóły w WDROZENIE).

## DWG

Zapis DWG wymaga zewnętrznego konwertera DXF → DWG. ODA File Converter nie jest
częścią repozytorium, a jego darmowa licencja nie pozwala używać go w usłudze dla
innych osób — publiczna strona oddaje więc DXF, który AutoCAD otwiera bezpośrednio.

## Licencja

[GNU Affero General Public License v3](LICENSE). Program korzysta z PyMuPDF
(AGPL-3.0), więc każdy, kto udostępnia go jako usługę sieciową, musi udostępnić
użytkownikom kod źródłowy swojej wersji.
