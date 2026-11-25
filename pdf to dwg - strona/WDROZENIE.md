# PDF2DWG — strona WWW

Darmowa strona do konwersji wektorowych PDF → DWG/DXF bez limitu plików, bez
rejestracji i bez znaku wodnego. Konwersję robi pakiet `pdf2dxf` z katalogu
`..\pdf to dwg` (ten sam co w `PDF2DWG.exe`); ta część to serwer WWW, kolejka
zadań i strona.

## Struktura

```
app/
  main.py      serwer (Starlette): strona, API, limit rozmiaru, nagłówki bezpieczeństwa
  jobs.py      kolejka zadań, uruchamianie konwersji w osobnych procesach, sprzątanie
  worker.py    jedna konwersja (python -m app.worker KATALOG): PDF → DXF → DWG, podgląd, ZIP
  options.py   walidacja opcji z formularza, bezpieczna nazwa pliku
  settings.py  konfiguracja ze zmiennych PDF2DWG_*
  page.py      strona główna: teksty zależne od trybu (DWG albo tylko DXF)
  templates/index.html   szablon strony głównej
static/        style.css, app.js, favicon.svg (bez zewnętrznych bibliotek i CDN)
tests/         testy API (pytest)
Dockerfile, docker-compose.yml, Caddyfile, .env.example   wdrożenie na serwer
```

## Jak działa

1. Przeglądarka wysyła PDF (`POST /api/jobs`) z opcjami: format, wersja DWG,
   skala, jednostki, krzywe, strony, wypełnienia, warstwy, tekst.
2. Serwer sprawdza rozmiar i sygnaturę `%PDF`, zapisuje plik w katalogu zadania
   o losowym, niezgadywalnym identyfikatorze i wstawia zadanie do kolejki.
3. Każda konwersja działa w **osobnym procesie** z limitem czasu — trudny lub
   złośliwy PDF nie zawiesi serwera; po przekroczeniu czasu proces jest zabijany
   razem z potomnymi (np. konwerterem DWG).
4. Strona odpytuje `GET /api/jobs/{id}` (pozycja w kolejce, postęp, raport)
   i pokazuje przycisk „Pobierz DWG” (wiele stron → ZIP).
5. PDF jest kasowany zaraz po konwersji, wynik — po `RETENTION_MINUTES`
   (domyślnie 30 min) albo od razu po kliknięciu „Usuń”.

„Bez limitu” oznacza brak dziennych limitów i kont. Są tylko techniczne
zabezpieczenia serwera (rozmiar pliku, liczba stron naraz, czas konwersji,
długość kolejki, kilka plików naraz z jednego IP) — wszystkie w `.env`.

## Uruchomienie lokalne (Windows)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e "..\pdf to dwg" -r requirements-dev.txt
```

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8765
```

Strona: <http://localhost:8765>. Domyślnie bez DWG (oddaje DXF). Do testów na
własnym komputerze można użyć zainstalowanego ODA File Converter:

```powershell
$env:PDF2DWG_DWG_ENGINE = "oda"; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8765
```

Testy:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Konfiguracja (`.env`)

| Zmienna | Domyślnie | Znaczenie |
|---|---|---|
| `PDF2DWG_DWG_ENGINE` | `none` | `none` — tylko DXF (strona sama mówi wtedy o DXF i ukrywa wybór formatu); `command` — własne polecenie DXF→DWG; `oda` — ODA File Converter (tylko lokalnie, patrz niżej) |
| `PDF2DWG_DWG_COMMAND` | — | dla `command`: np. `dxf2dwg {input} {output} {version}` |
| `PDF2DWG_DWG_VERSIONS` | wszystkie | wersje DWG pokazywane na stronie |
| `PDF2DWG_SOURCE_URL` | — | link „Kod źródłowy” w stopce (wymóg AGPL) |
| `PDF2DWG_CONTACT` | — | e-mail lub URL kontaktu w stopce |
| `PDF2DWG_WORKERS` | `2` | konwersje równolegle (≈ liczba rdzeni) |
| `PDF2DWG_MAX_UPLOAD_MB` | `50` | największy plik |
| `PDF2DWG_MAX_PAGES` | `100` | stron z jednego pliku naraz |
| `PDF2DWG_JOB_TIMEOUT` | `180` | sekund na jedną konwersję |
| `PDF2DWG_JOB_MEMORY_MB` | `1500` | pamięci na jedną konwersję (0 = bez limitu); `WORKERS × JOB_MEMORY_MB` musi zmieścić się w `mem_limit` z `docker-compose.yml` |
| `PDF2DWG_MAX_QUEUE` | `50` | zadań w kolejce (więcej → „serwer zajęty”) |
| `PDF2DWG_MAX_ACTIVE_PER_CLIENT` | `6` | niezakończonych zadań z jednego IP |
| `PDF2DWG_RETENTION_MINUTES` | `30` | po ilu minutach wynik jest kasowany |
| `PDF2DWG_MIN_FREE_MB` | `1024` | poniżej tylu MB wolnego dysku nowe pliki nie są przyjmowane |
| `PDF2DWG_DATA_DIR` | `%TEMP%\pdf2dwg-web` | katalog zadań (czyszczony przy starcie) |

## Uruchomienie strony w internecie — krok po kroku

Potrzebne: domena, serwer VPS z Linuksem, konto GitHub. Koszt: domena kilkadziesiąt
zł rocznie, serwer od ok. 20–40 zł miesięcznie.

### 1. Publiczne repozytorium z kodem (wymóg AGPL)

**Uwaga:** repozytorium git konwertera (`..\pdf to dwg`) ma w historii pliki z
`samples\` (rysunki firmowe) — **nigdy go nie wypychaj**, bo historia zostałaby
opublikowana razem z nimi. Publiczne jest osobne, czyste repozytorium
`..\pdf2dwg` (dwa katalogi obok siebie, licencja AGPL-3.0 w `LICENSE` — PyMuPDF
wymaga udostępnienia całości na AGPL albo kupna licencji komercyjnej od Artifex).
Zawartość kopiuje do niego skrypt z listą dozwolonych plików (bez `samples\`,
wyników, `.venv\`, `.env`; plik PDF/DXF/DWG/ZIP/EXE przerywa eksport):

```powershell
.\.venv\Scripts\python.exe scripts\eksport_publiczny.py
```

Potem w `..\pdf2dwg`: `git status`, `git diff`, commit i `git push`. Ustaw tam
autora commitów na adres `…@users.noreply.github.com` z GitHuba, żeby nie
publikować służbowego e-maila.

### 2. Domena

Kup domenę u dowolnego rejestratora (OVH, nazwa.pl, home.pl, Cloudflare…).

### 3. Serwer VPS

Ubuntu 24.04 LTS, x86-64, **2 vCPU, 4 GB RAM**, 40 GB dysku — np. Hetzner Cloud
albo OVHcloud. Przy zakładaniu dodaj klucz SSH (logowanie bez hasła). Klucz
tworzysz na Windows w PowerShell:

```powershell
ssh-keygen -t ed25519
```

i wklejasz w panelu dostawcy zawartość pliku `C:\Users\<ty>\.ssh\id_ed25519.pub`.

### 4. DNS

W panelu domeny dodaj rekord **A**: nazwa `@`, wartość = adres IP serwera (opcjonalnie
drugi rekord A dla `www`). Po kilku–kilkudziesięciu minutach `nslookup twojadomena.pl`
ma pokazywać IP serwera.

### 5. Przygotowanie serwera

```bash
ssh root@ADRES_IP
apt update && apt upgrade -y
apt install -y git unattended-upgrades          # automatyczne poprawki bezpieczeństwa systemu
curl -fsSL https://get.docker.com | sh          # Docker + docker compose
ufw allow OpenSSH && ufw allow 80,443/tcp && ufw allow 443/udp && ufw enable
```

Gdy logowanie kluczem działa, wyłącz logowanie hasłem: w `/etc/ssh/sshd_config`
ustaw `PasswordAuthentication no`, potem `systemctl restart ssh`.

### 6. Kod i konfiguracja

```bash
git clone https://github.com/TWOJ-LOGIN/pdf2dwg.git
cd "pdf2dwg/pdf to dwg - strona"
cp .env.example .env
nano .env        # SITE_ADDRESS=twojadomena.pl, PDF2DWG_SOURCE_URL=https://github.com/TWOJ-LOGIN/pdf2dwg, PDF2DWG_CONTACT=…
```

### 7. Start

```bash
docker compose up -d --build     # pierwsze budowanie trwa kilka minut
docker compose ps                # obie usługi „running”, web „healthy”
docker compose logs -f web       # podgląd logów (Ctrl+C kończy podgląd, nie stronę)
```

Caddy sam pobiera i odnawia certyfikat HTTPS. Otwórz `https://twojadomena.pl`,
przekonwertuj próbny PDF. Port 8000 aplikacji nie jest wystawiany na zewnątrz —
ruch idzie tylko przez Caddy.

### 8. Przed ogłoszeniem strony

- polityka prywatności (patrz „Dane osobowe (RODO)” niżej),
- sprawdź link „Kod źródłowy” w stopce.

### 9. Aktualizacje (raz w miesiącu i po każdej zmianie kodu)

```bash
cd "pdf2dwg/pdf to dwg - strona" && git pull && docker compose up -d --build
```

Najważniejsza dla bezpieczeństwa jest aktualna wersja **PyMuPDF** (to ona czyta
PDF-y od obcych osób): podnieś wersję w `requirements.txt`, gdy wyjdzie nowa, i
przebuduj obraz. GitHub może o tym przypominać (Dependabot).

## Bezpieczeństwo — złośliwe PDF-y

Serwer nigdy nie wykonuje PDF-a: PyMuPDF tylko odczytuje z niego geometrię i tekst,
a DXF/DWG jest zapisywany od zera. JavaScript, akcje „Launch”, załączniki i makra
z PDF nie trafiają do wyniku — nie ma czego przenieść. Główne ryzyka to więc
pliki-bomby (zjadające pamięć i czas) oraz błąd w samej bibliotece PDF. Warstwy ochrony:

| Zagrożenie | Ochrona |
|---|---|
| plik-bomba: mały PDF, ogromna treść | limit pamięci na konwersję (`JOB_MEMORY_MB`, pomiar co 0,25 s, zabicie całego drzewa procesów), limit czasu, limit stron, kolejka i limit zadań na IP |
| zawieszenie / awaria biblioteki | każda konwersja w osobnym procesie; serwer WWW działa dalej |
| błąd w PyMuPDF wykorzystany do przejęcia procesu | kontener bez uprawnień (`cap_drop: ALL`, `no-new-privileges`, użytkownik bez roota, system plików tylko do odczytu), **bez dostępu do internetu** (sieć wewnętrzna), aktualizacje PyMuPDF |
| XSS / wstrzyknięcie nagłówków przez nazwę pliku | nazwa czyszczona (`safe_stem`), strona wstawia tekst wyłącznie jako tekst, CSP bez skryptów inline, `Content-Disposition` kodowany |
| podszycie innego pliku pod PDF | sygnatura `%PDF`, plik nigdy nie jest odsyłany ani wyświetlany |
| podgląd cudzych wyników | losowy, niezgadywalny identyfikator zadania, pliki kasowane po 30 min |
| zapchanie dysku | wynik ograniczony limitem pamięci, minimum wolnego miejsca, automatyczne sprzątanie |

Skaner antywirusowy (np. ClamAV) nie jest potrzebny: PDF nie jest przechowywany
ani przekazywany dalej (kasowany zaraz po konwersji), a wynik nie zawiera nic z
oryginalnego pliku poza liniami i tekstem.

Sprawdzone spreparowanymi plikami (25.11.2026): PDF z JavaScriptem, akcją Launch
i załączonym `.exe` → czysty DXF z jedną linią; tekst ze znakami nowej linii
udający kody DXF → poprawny DXF, bez dodatkowych obiektów; bomba 1 mln odcinków
(5 MB, bez limitu zajmowała 3,5 GB i >3 min) → przerwana po ok. 9 s z komunikatem;
obraz 20000×20000 px, rekurencyjny XObject, 5000 stron, strona 14400×14400 pt,
PDF zaszyfrowany i uszkodzony → szybki, czytelny komunikat; nazwa pliku z HTML i
`\r\n` → bezpieczna nazwa. Serwer odpowiadał przez cały test w kilka ms.

## Sprawy prawne — przeczytać przed publikacją

### ODA File Converter (zapis DWG)

Darmowy ODA File Converter jest objęty „ODA Community User Agreement”
(wersja 09-2025). Punkt 3.1.1 (Restrictions, b) zabrania użycia go
„in any time-sharing or service bureau arrangement” — czyli właśnie jako
silnika usługi konwertującej pliki innych osób. Dlatego:

- **nie wolno** ustawić `PDF2DWG_DWG_ENGINE=oda` na publicznej stronie;
- `oda` jest tylko do testów na własnym komputerze (tak jak `PDF2DWG.exe`).

Legalne drogi do DWG na stronie:

1. **ACadSharp** (biblioteka .NET na licencji MIT, zapisuje DWG) — mały program
   DXF→DWG podłączony przez `PDF2DWG_DWG_ENGINE=command`. Wymaga sprawdzenia, czy
   pliki otwierają się bez naprawy w AutoCAD/BricsCAD.
2. **LibreDWG** (`dxf2dwg`, GPL-3.0) — zapis DWG jest tam eksperymentalny.
3. **Płatna licencja ODA** obejmująca usługi web/SaaS.
4. **Tylko DXF** (`none`) — legalne od razu; AutoCAD otwiera DXF bezpośrednio.

**Decyzja (25.11.2026): na start strona działa w trybie tylko DXF.** Tytuł,
nagłówek, kroki i FAQ mówią wtedy o DXF („Konwerter PDF do DXF”, „Dlaczego DXF,
a nie DWG?”), a wybór formatu jest ukryty — strona nie obiecuje DWG, którego nie
oddaje. Po podłączeniu legalnego silnika DWG (`command`) teksty same wracają do
DWG, bez zmian w kodzie.

### PyMuPDF (AGPL-3.0)

Przy usłudze sieciowej AGPL wymaga udostępnienia użytkownikom kodu źródłowego
całego programu (konwertera i strony). Najprościej: publiczne repozytorium
i link w `PDF2DWG_SOURCE_URL`. **Uwaga:** katalog `samples\` konwertera zawiera
rysunki firmowe — nie publikować go. Alternatywa bez AGPL: backend na
`pypdfium2` (nowa implementacja `PdfBackend`).

### Dane osobowe (RODO)

Strona nie używa cookies ani analityki, pliki są kasowane automatycznie, a
logi serwera zawierają adres IP i nazwę pliku. Przy publicznej stronie dodaj
politykę prywatności (kto jest administratorem, jak długo trzymane są pliki
i logi) i ustaw rotację logów Dockera.

## Stan sprawdzenia

- Testy API: 17/17 (strona w trybie DXF i DWG, DXF, wiele stron → ZIP, DWG przez
  polecenie, awaria DWG → DXF, limit rozmiaru, skan, limit stron, przekroczenie
  czasu, limit pamięci, złośliwa zawartość PDF, brak ścieżek serwera w błędach,
  limit na IP, usuwanie, walidacja opcji).
- Tryb tylko DXF (jak na publicznej stronie): rysunek testowy z `samples` → DXF w ~2 s,
  730 obiektów (jak w `.exe`); żądanie DWG jest odrzucane.
- Lokalnie z ODA: ten sam rysunek → DWG `AC1032` w ~3 s, 730 obiektów.
- Strona sprawdzona w przeglądarce (jasny/ciemny motyw, wąski ekran), bez błędów w konsoli.
- **Nie sprawdzone:** budowanie obrazu Dockera i działanie na Linuksie (na tym
  komputerze nie ma Dockera ani WSL) — w tym linuksowy pomiar pamięci (`/proc`),
  obniżenie priorytetu konwersji i ustawienia izolacji z `docker-compose.yml`.
  Pierwsze `docker compose up` na serwerze jest pierwszym testem tej części.
