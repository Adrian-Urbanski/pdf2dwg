# pdf2dxf

Konwerter **wektorowych** rysunków PDF (eksporty z AutoCAD, Revit, ArchiCAD,
Inkscape, programów graficznych itp.) do plików **DXF** otwieralnych
w AutoCAD, BricsCAD, DraftSight, LibreCAD i QCAD. Pełna specyfikacja:
[SPEC.md](SPEC.md). Opis działania i wszystko, co potrzebne do odtworzenia
programu (algorytmy, stałe, okno, budowanie `.exe`, testy):
[DOKUMENTACJA.md](DOKUMENTACJA.md).

Co jest przenoszone: linie, polilinie, prostokąty, krzywe Béziera (jako
`SPLINE` albo polilinie), okręgi i łuki rozpoznane z krzywych (`CIRCLE`,
`ARC`, polilinie z łukami), wypełnienia (`HATCH`), tekst (`TEXT`, polskie
znaki bez zmian), kolory, grubości linii, linie przerywane i warstwy.
Obsługiwane są pliki wielostronicowe, strony obrócone, skala i jednostki.
Skany są wykrywane i zgłaszane — narzędzie ich nie wektoryzuje.

## Instalacja

Wymagany Python 3.10+ (projekt powstał na 3.15).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[preview]"
```

Dodatki: `[preview]` — podgląd PNG (matplotlib); `[dev]` — testy (pytest,
pymupdf-fonts, matplotlib).

## Aplikacja okienkowa: `PDF2DWG.exe`

Najprostszy sposób: uruchom `dist\PDF2DWG.exe`, **upuść pliki PDF** na
listę (albo kliknij i wybierz), sprawdź podgląd i kliknij **„Konwertuj”**.
Obok każdego PDF powstaje plik **DWG** o tej samej nazwie. PDF upuszczony
na ikonę `PDF2DWG.exe` też trafia na listę i czeka na „Konwertuj”.

- **Lista plików** (lewa góra): `•` czeka, `✓` skonwertowany, `✗` błąd.
  „Konwertuj” przetwarza pliki oczekujące i z błędem; gdy wszystkie są już
  skonwertowane — wszystkie ponownie (np. po zmianie skali). Dodanie nowych
  plików usuwa z listy te gotowe.
- **Podgląd** (prawa strona): strona PDF zaznaczona na liście, przyciski
  ◀ ▶ przełączają strony.
- **Ustawienia** (lewy dół): jednostki, skala rysunku (`50` albo `1:50`),
  wersja DWG, sposób zapisu krzywych (SPLINE albo polilinie dla CNC) i to,
  czy zachować też plik DXF.
- Log pokazuje raport dla każdego pliku, a przycisk „Otwórz folder
  z wynikiem” otwiera katalog z DWG.

- Do zapisu DWG potrzebny jest zainstalowany **ODA File Converter** (okno
  pokazuje, czy został znaleziony, i ma przycisk do strony pobierania). Bez
  niego powstaje sam DXF.
- `.exe` zawiera Pythona i wszystkie biblioteki — na innym komputerze nie
  trzeba niczego instalować poza ODA File Converter.
- Pierwsze uruchomienie trwa kilka sekund (program rozpakowuje się do
  katalogu tymczasowego). Windows SmartScreen może ostrzec przed
  niepodpisanym programem — „Więcej informacji” → „Uruchom mimo to”.
- Gdyby program nie wystartował, szczegóły błędu są w
  `%TEMP%\PDF2DWG-blad.txt`.

Bez budowania `.exe` to samo okno otwiera `.\.venv\Scripts\pdf2dxf-gui.exe`
(wymaga `pip install -e ".[gui]"`).

### Budowanie `.exe`

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[build]"
```

```powershell
.\.venv\Scripts\python.exe scripts\build_exe.py
```

Wynik: `dist\PDF2DWG.exe` (~52 MB, jeden plik). `scripts\build_exe.py
--console` buduje wariant diagnostyczny `PDF2DWG-console.exe`, który
pokazuje błędy w oknie konsoli.

## Użycie z wiersza poleceń

```powershell
.\.venv\Scripts\pdf2dxf.exe rysunek.pdf
```

To samo działa jako `python -m pdf2dxf rysunek.pdf`. Wynik trafia obok PDF:
`rysunek.dxf` (jedna strona) albo `rysunek_p1.dxf`, `rysunek_p2.dxf`, …
(wiele stron).

### Przykłady

Arkusz w skali 1:50, wymiary rzeczywiste w milimetrach, z podglądem PNG:

```powershell
.\.venv\Scripts\pdf2dxf.exe plan.pdf -o wyniki\ --scale 50 --preview
```

Strony 1 i 3–5, wszystkie obok siebie w jednym pliku, w metrach:

```powershell
.\.venv\Scripts\pdf2dxf.exe projekt.pdf --pages 1,3-5 --single-file --units m -o projekt.dxf
```

Do maszyn CNC / programów bez obsługi SPLINE — krzywe jako polilinie,
odcinki sklejone w ciągłe kontury, bez tekstu i wypełnień:

```powershell
.\.venv\Scripts\pdf2dxf.exe detal.pdf --curves polyline --join --no-text --fills ignore
```

Warstwy z PDF (OCG), jeśli plik je ma:

```powershell
.\.venv\Scripts\pdf2dxf.exe rysunek.pdf --layers by-ocg
```

### Opcje

| Opcja | Domyślnie | Znaczenie |
|---|---|---|
| `-o OUT` | obok PDF | plik `.dxf` albo katalog (istniejący lub zakończony `\`/`/`) |
| `--pages 1,3-5` | wszystkie | strony do konwersji (od 1) |
| `--single-file` | — | wszystkie strony obok siebie w jednym DXF (odstęp 10 % szerokości) |
| `--units mm\|cm\|m\|in\|pt` | `mm` | jednostki DXF (`$INSUNITS`; `pt` = bez jednostek) |
| `--scale N` | `1` | rysunek w skali 1:N — współrzędne × N (wymiary rzeczywiste) |
| `--curves spline\|polyline` | `spline` | krzywe jako `SPLINE` albo spłaszczone `LWPOLYLINE` |
| `--flatten-tol MM` | `0.01` | tolerancja spłaszczania krzywych, w mm na arkuszu |
| `--detect-arcs` / `--no-detect-arcs` | włączone | rozpoznawanie okręgów i łuków w krzywych |
| `--join` | — | sklejanie odcinków o wspólnych końcach w polilinie |
| `--layers by-color\|by-ocg\|single` | `by-color` | warstwy `PDF_RRGGBB`, z warstw PDF, albo jedna `PDF` |
| `--fills hatch\|outline\|ignore` | `hatch` | wypełnienia jako `HATCH`, jako kontur, albo pominięte |
| `--no-text` | — | pomija tekst |
| `--merge-text` | — | łączy fragmenty tekstu z jednej linii o tym samym stylu |
| `--text-height-factor F` | `0.7` | wysokość `TEXT` = rozmiar fontu × F |
| `--dxf-version` | `R2010` | `R2000`, `R2004`, `R2007`, `R2010`, `R2013`, `R2018` |
| `--preview` | — | podgląd PNG obok każdego DXF (wymaga `[preview]`) |
| `--dwg` | — | dodatkowo DWG obok każdego DXF (wymaga ODA File Converter) |
| `--dwg-version` | `R2018` | `R2000` … `R2018` |
| `--oda-path PATH` | szukany sam | ścieżka do `ODAFileConverter.exe` lub jego katalogu |
| `-v` | — | komunikaty diagnostyczne |

Grubość linii nie podlega skali (to cecha wydruku); wysokość tekstu i długości
kresek linii przerywanych — tak.

### Raport i kody wyjścia

Po konwersji drukowany jest raport, np.:

```
pdf2dxf: STOJAK BUTY.pdf
  strona 1 → out\STOJAK BUTY.dxf
    encje: CIRCLE 32, LINE 252, LWPOLYLINE 98, SPLINE 348 (razem 730)
    usunięte duplikaty: 0
  podgląd: out\STOJAK BUTY.png
```

| Kod | Znaczenie |
|---|---|
| 0 | OK |
| 1 | błąd (brak pliku, uszkodzony / zaszyfrowany PDF, błąd zapisu, nieudana konwersja DWG) |
| 2 | złe argumenty (także `--pages` bez żadnej istniejącej strony) |
| 3 | brak danych wektorowych — PDF wygląda na skan albo jest pusty |

### Podgląd (`--preview`)

PNG renderowany jest z **gotowego DXF** (ezdxf + matplotlib), na białym tle,
dłuższy bok 2000 px — pokazuje to, co zobaczy program CAD. Służy do szybkiej
kontroli wzrokowej względem oryginału.

### DWG (`--dwg`)

Podstawowym wynikiem jest DXF — otwiera go każdy program CAD. Z opcją `--dwg`
każdy zapisany DXF jest dodatkowo konwertowany do DWG (obok, z tą samą
nazwą) darmowym programem **ODA File Converter** (Open Design Alliance),
który trzeba pobrać i zainstalować osobno:
<https://www.opendesign.com/guestfiles/oda_file_converter>.

```powershell
.\.venv\Scripts\pdf2dxf.exe rysunek.pdf --dwg --dwg-version R2018
```

Program jest szukany kolejno: `--oda-path` → zmienna środowiskowa
`PDF2DXF_ODA_PATH` → `PATH` → `C:\Program Files\ODA\ODAFileConverter*\`
(najnowsza wersja) → typowe miejsca na macOS/Linux. Jeśli jest gdzie
indziej, wskaż plik `ODAFileConverter.exe` (albo jego katalog):

```powershell
.\.venv\Scripts\pdf2dxf.exe rysunek.pdf --dwg --oda-path "D:\Narzędzia\ODA\ODAFileConverter.exe"
```

Gdy konwertera nie ma albo konwersja się nie uda, DXF i tak zostaje
zapisany, program wypisuje, skąd pobrać ODA i jak go wskazać, i kończy się
kodem 1. Alternatywą jest `dxf2dwg` z **LibreDWG**, ale zapis DWG jest tam
eksperymentalny, dlatego nie jest używany.

## Testy

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

Testowe PDF-y są generowane w fixture'ach PyMuPDF (geometria znana co do
liczby); każdy wygenerowany DXF jest ponownie otwierany i audytowany przez
ezdxf. Test wizualny (rasteryzacja PDF vs PNG z DXF, IoU masek ciemnych
pikseli > 0.9) ma znacznik `slow` — pominięcie: `pytest -m "not slow"`.
Skrypt `scripts/recon_pymupdf.py` wypisuje rzeczywistą strukturę danych
PyMuPDF w zainstalowanej wersji.

## Architektura

```
PDF → backends/pymupdf_backend.py → model.py (pt, Y w dół)
    → transform.py (obrót strony, odbicie Y, jednostki, skala)
    → postprocess.py (zaokrąglenie, duplikaty, łuki, --join, --merge-text)
    → writer.py (ezdxf) → [preview.py] → [dwg.py → ODA File Converter]
```

`converter.py` spina potok, `cli.py` obsługuje argumenty i raport. Backend
nie importuje ezdxf, writer nie importuje PyMuPDF — łączy je tylko model
pośredni. Ekstrakcja jest schowana za interfejsem `PdfBackend`
(`backends/base.py`).

**Licencja zależności:** PyMuPDF jest na licencji AGPL-3.0. Do użytku
własnego nie ma to znaczenia; przy rozpowszechnianiu zamkniętego
oprogramowania potrzebna byłaby licencja komercyjna Artifex albo podmiana
backendu (np. na `pypdfium2`) — wystarczy nowa implementacja `PdfBackend`.
Dotyczy to także `PDF2DWG.exe`, który zawiera PyMuPDF — przed przekazaniem
go poza firmę trzeba spełnić warunki AGPL (np. udostępnić kod źródłowy).

## Decyzje projektowe

### Środowisko i zależności

- **PyMuPDF < 2.** PyMuPDF 2.x ma twardą zależność od `onnxruntime`, które nie
  ma kół dla Pythona 3.15 (na nim powstawał projekt). Struktury danych zostały
  sprawdzone na PyMuPDF 1.28.2, dlatego zależność jest zawężona do `>=1.24,<2`.
- **Katalog główny projektu** to katalog z `SPEC.md` (a nie podkatalog
  `pdf2dxf/`, jak w drzewie z SPEC).
- **Font do testów z polskimi znakami:** `pymupdf-fonts` (Noto Sans, nazwa
  `"notos"`) — zależność tylko w `[dev]`.

### Model i potok

- **Dodatkowy moduł `converter.py`** (spoza drzewa z SPEC) spina potok:
  wybór stron → ekstrakcja → transformacja → postprocessing → zapis. CLI
  tylko parsuje argumenty i drukuje raport, więc ten sam potok może
  wykorzystać GUI.
- **Model pośredni ma dwie przestrzenie** (`PageData.space`): `"pdf"`
  (pt, Y w dół, strona nieobrócona — wynik backendu) i `"dxf"` (jednostki
  rysunku, Y w górę, obrót strony zastosowany — wynik `transform.py`).
  Grubość linii i wzory kresek zostają w pt w obu przestrzeniach; writer
  przelicza je przez `PageData.unit_scale`.
- **Obrót strony** liczony jest w `transform.py` bez PyMuPDF (macierz
  identyczna z `page.rotation_matrix` — sprawdza to test).
- Podścieżka uznana za zamkniętą z tolerancją 0.001 pt ma koniec
  „dociągnięty” dokładnie do początku, więc w DXF nie powstają zdublowane
  wierzchołki.

### Zachowanie dla użytkownika

- **Nazwy plików:** gdy powstaje jeden plik (jedna wybrana strona albo
  `--single-file`) — `nazwa.dxf`; przy wielu stronach `nazwa_p1.dxf`,
  `nazwa_p2.dxf`, … Domyślnie pliki trafiają obok PDF. `-o` przyjmuje plik
  `.dxf` albo katalog (istniejący lub zakończony `/`).
- **`--flatten-tol` jest w milimetrach na arkuszu** (przed skalą,
  niezależnie od `--units`): 0.01 mm na papierze to rozsądna dokładność
  niezależnie od tego, czy rysunek jest w mm, czy w m.
- `--pages` z numerami spoza dokumentu: nieistniejące strony są pomijane
  z ostrzeżeniem; gdy nie zostaje żadna — kod wyjścia 2.
- Oprócz `$INSUNITS` ustawiane jest `$MEASUREMENT` (1 = metryczne, 0 dla
  cali) oraz widok startowy na cały rysunek.

### Krzywe, kolory, warstwy, wypełnienia (faza 2)

- **`--curves spline`:** podścieżka jest dzielona przez
  `ezdxf.path.to_bsplines_and_vertices` — ciągi krzywych → `SPLINE`
  (rozdzielane w narożnikach bez ciągłości G1), ciągi odcinków →
  `LINE`/`LWPOLYLINE`. To ta sama logika co w `render_splines_and_polylines`
  z SPEC, ale bez 3D `POLYLINE`, które ta funkcja tworzy dla odcinków
  (`LWPOLYLINE` jest lżejsza i spójna z resztą rysunku). W zamkniętej
  podścieżce punkt startu przesuwany jest na początek krzywej, żeby linie
  sprzed i zza punktu startu tworzyły jedną polilinię.
- **Kolor czarny** = wszystkie składowe ≤ 0.05 (tolerancja na „głęboką
  czerń” z konwersji CMYK). Dostaje tylko ACI 7, **bez** koloru prawdziwego,
  bo kolor prawdziwy ma pierwszeństwo i czarne linie zniknęłyby na czarnym
  tle CAD. Pozostałe kolory: kolor prawdziwy + najbliższy ACI.
- Kolor jest ustawiany jawnie na encji (nie BYLAYER). Warstwy `PDF_RRGGBB`
  mają kolor odpowiadający nazwie; warstwy z OCG i warstwa `PDF` — ACI 7.
- **Grubości:** ustawiane jest `$LWDISPLAY = 1`, żeby CAD od razu je
  pokazywał. Grubość 0 z PDF (najcieńsza linia) → lineweight 0.
- **Linie przerywane:** długości kresek **skalują się razem z geometrią**
  (`× k`, także przez `--scale`), żeby wzór nakładał się na oryginał —
  w odróżnieniu od grubości. Przesunięcie fazy wzoru jest pomijane (typy
  linii DXF go nie mają); tablica o nieparzystej liczbie wartości jest
  podwajana, jak w PDF.
- **HATCH:** kontury to polilinie (krzywe spłaszczone z `--flatten-tol`) —
  najlepiej obsługiwane przez różne programy CAD. Styl kreskowania „normal”
  (wyspy na przemian = reguła even-odd). Dla reguły **nonzero** zostają tylko
  kontury, na których zmienia się stan wypełnienia (np. wewnętrzny kontur
  o tym samym kierunku obiegu nie robi dziury). Przezroczystość wypełnień
  i linii jest przenoszona.
- **Tło:** białe (składowe ≥ 0.98) wypełnienie o obrysie zajmującym ≥ 90 %
  strony jest zawsze pomijane.
- `--fills outline` rysuje kontur w kolorze wypełnienia tylko dla kształtów
  bez obrysu (przy `fs` obrys już istnieje).
- Element `re` z orientacją 1 to obieg przeciwny do wskazówek zegara na
  ekranie (jak operator PDF `re`); PyMuPDF zamienia na `re` tylko prostokąty
  rysowane w tym kierunku. Kierunek jest odtwarzany, bo liczy się dla reguły
  nonzero.

### Tekst (faza 3)

- Jeden styl tekstu `PDF_TEXT` z fontem `arial.ttf` (polskie znaki); nazwa
  oryginalnego fontu zostaje w modelu, ale nie trafia do DXF.
- Kąt `TEXT` liczony jest z `dir` linii po zastosowaniu obrotu strony
  i odbicia osi Y; zapisywany w zakresie [0°, 360°).
- **Tekst niewidoczny** (tryb renderowania 3 — typowa warstwa OCR skanów,
  albo `alpha = 0`) jest pomijany z ostrzeżeniem w raporcie. Spany z samych
  białych znaków są pomijane; tabulatory zamieniane na spacje, pozostałe znaki
  sterujące usuwane.
- Spany z niezmapowanymi znakami (`U+FFFD`, font bez ToUnicode) trafiają do
  DXF, ale raport ostrzega o ich liczbie.
- **`--merge-text`** łączy kolejne fragmenty o tym samym foncie, rozmiarze,
  kolorze, kryciu i kącie, leżące na jednej linii bazowej, gdy przerwa między
  nimi ≤ 0.5 × rozmiar fontu (spacja wstawiana przy przerwie > 0.15 ×
  rozmiar). Działa geometrycznie, więc łączy też fragmenty, które PyMuPDF
  rozdzielił na osobne linie lub spany (np. „Abc”, „ ”, „Def” przy
  szerszym odstępie). Długość spanu wzdłuż linii bazowej odtwarzana jest
  z jego prostokąta otaczającego (`TextItem.width`).

### Postprocessing i strony (faza 4)

- Tolerancje postprocessingu są wyrażone **w pt na arkuszu** i przeliczane
  przez współczynnik `k`, więc wynik nie zależy od `--units` ani `--scale`.
- **Odcinki „zerowej długości”** to segmenty ≤ 0.005 pt (≈ 0.002 mm na
  arkuszu), nie tylko dokładnie zerowe: eksporty (np. macOS Quartz) zapisują
  współrzędne w float32 i po operatorze `h` zostaje mikroskopijny odcinek
  zamykający, który psułby rozpoznawanie okręgów. Sąsiednie segmenty są po
  usunięciu dociągane do siebie.
- **Deduplikacja** działa na całych podścieżkach (niezależnie od kierunku
  i — dla zamkniętych — punktu startu) w obrębie identycznego stylu, na
  siatce 0.01 pt. Dodatkowo usuwane są pojedyncze odcinki pokrywające się
  z bokiem innej polilinii tego samego stylu. Kształty wypełnione są
  porównywane w całości.
- **Łuki:** pojedyncza krzywa Béziera jest uznawana za łuk ≤ 91°, gdy
  punkty krzywej leżą na okręgu z dokładnością 0.1 % promienia (min.
  0.005 pt). Kolejne łuki tego samego okręgu są łączone (także przez punkt
  startu zamkniętej ścieżki; zapas 0.5° na sumę kątów). Wynik: pełny okrąg →
  `CIRCLE`, pojedynczy łuk → `ARC`, odcinki + łuki → `LWPOLYLINE` z
  wypukłościami (bulge) — np. prostokąt z zaokrąglonymi rogami to jedna
  polilinia, którą łatwo zwymiarować. Kontury `HATCH` złożone z odcinków
  i łuków też są zapisywane dokładnie (bulge), bez spłaszczania.
- **`--detect-arcs` ma pierwszeństwo przed `--curves polyline`:** okrąg
  pozostaje `CIRCLE` także w trybie polilinii (encje `CIRCLE`/`ARC` są
  dokładne i obsługiwane wszędzie, także w programach CNC). Spłaszczony okrąg
  daje `--curves polyline --no-detect-arcs`.
- **`--join`** łączy otwarte podścieżki o wspólnych końcach i tym samym
  stylu wyłącznie przez węzły, w których spotykają się dokładnie dwa końce —
  przy rozgałęzieniach (T, X) wynik byłby przypadkowy. Połączone polilinie
  trafiają na koniec kolejności rysowania.
- **Skany:** strona jest uznawana za rastrową, gdy obrazy zakrywają ≥ 30 %
  jej powierzchni, a podścieżek + fragmentów tekstu jest ≤ 5. Taka strona
  jest pomijana (nie powstaje dla niej plik). Strona bez żadnej treści też
  jest pomijana z ostrzeżeniem. Kod 3 zwracany jest, gdy żadna strona nie
  ma danych wektorowych — komunikat o skanie tylko wtedy, gdy była strona
  rastrowa. Strona wektorowa z obrazami (np. logo) dostaje ostrzeżenie, że
  obrazy nie są przenoszone.
- **`--single-file`:** strony obok siebie wzdłuż osi X, z odstępem 10 %
  szerokości strony.
- Raport zawsze podaje liczbę usuniętych duplikatów (także 0), a przy
  `--join` — liczbę połączonych odcinków.

### Podgląd i weryfikacja (faza 5)

- Podgląd renderowany jest **z zapisanego DXF**, nie z PDF — ma pokazywać
  wynik konwersji. Białe tło, ACI 7 jako czarny, dłuższy bok 2000 px.
  Błąd podglądu (np. brak matplotlib) jest ostrzeżeniem w raporcie, nie
  przerywa konwersji.
- Backend matplotlib w ezdxf 1.4 przekazuje lineweight w milimetrach jako
  szerokość linii w punktach, przez co linie wychodzą ~2.8× za cienkie.
  Podgląd kompensuje to (`lineweight_scaling = 72/25.4`), żeby grubości
  odpowiadały wydrukowi; wyszło to w teście wizualnym.
- **Test wizualny (15):** strona PDF rasteryzowana przez PyMuPDF i PNG z DXF
  w tej samej rozdzielczości (100 dpi, ten sam obszar strony), maski
  ciemnych pikseli rozszerzone o 2 px, IoU > 0.9 (uzyskane: 0.97 dla obu
  trybów krzywych). Tekst jest pominięty w tym teście, bo font zastępczy
  ma inne kształty liter.

### DWG (faza 6)

- **Własne wyszukiwanie ODA File Converter.** Domyślna ścieżka w ezdxf
  (`C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe`) nie pasuje
  do nowszych instalatorów, które tworzą katalog z numerem wersji
  (`ODAFileConverter 25.x.0`). Program szuka więc katalogów
  `ODA\ODAFileConverter*` (wybiera najnowszą wersję), sprawdza też `PATH`,
  opcję `--oda-path` i zmienną `PDF2DXF_ODA_PATH`, a znalezioną ścieżkę
  przekazuje do `ezdxf.addons.odafc` tylko na czas działania programu
  (bez zmiany konfiguracji ezdxf na dysku). Jawnie wskazana ścieżka, która
  nie istnieje, jest błędem — program nie użyje po cichu innej instalacji.
- **Dodatkowa opcja `--oda-path`** (spoza SPEC) — SPEC wymaga komunikatu „jak
  wskazać ścieżkę”, a opcja jest najprostszym sposobem.
- **Brak DWG = kod wyjścia 1**, mimo że DXF jest zapisany: użytkownik prosił
  o DWG i go nie dostał, a skrypty powinny to wykryć.
- ezdxf 1.4.5 nie zgłasza błędu, gdy ODA nie utworzy pliku wynikowego (w
  `odafc.convert` brakuje `raise`), dlatego po konwersji sprawdzane jest,
  czy plik DWG istnieje i nie jest pusty.
- Konwersja jest wywoływana z audytem ODA (`audit=True`); istniejący plik
  DWG jest zastępowany.
- Logika jest testowana z atrapą `odafc.convert`; test z prawdziwym ODA
  (`test_real_oda_conversion`, znacznik `slow`) uruchamia się automatycznie,
  gdy program zostanie znaleziony, i sprawdza nagłówek `AC1032` oraz odczyt
  DWG z powrotem.

### Aplikacja okienkowa i `.exe` (faza 7)

- Okno służy przede wszystkim do zamiany PDF → **DWG**: konwersja zawsze
  zapisuje DXF, a potem DWG; DXF pośredni jest **usuwany**, gdy DWG powstał
  i nie zaznaczono „Zachowaj też plik DXF”. Gdy DWG nie powstanie (brak ODA,
  błąd), DXF zostaje.
- Wynik trafia **obok pliku PDF** (bez wyboru katalogu — najmniej kliknięć).
- Upuszczone lub wybrane pliki trafiają na listę i są konwertowane dopiero
  po kliknięciu „Konwertuj” (jak w SPEC). Ustawienia są brane w chwili
  kliknięcia; pliki są przetwarzane po kolei w osobnym wątku (okno nie
  zamarza). Gotowe pliki znikają z listy przy dodaniu nowych, a „Konwertuj”
  przy samych gotowych plikach konwertuje je ponownie — to pozwala zmienić
  skalę i powtórzyć konwersję bez ponownego dodawania pliku.
- Podgląd pokazuje **stronę PDF** (render PyMuPDF przez nową metodę
  `PdfBackend.render_png`, więc okno nie importuje PyMuPDF bezpośrednio),
  a nie wynik DWG — do tego potrzebny byłby matplotlib, który zwiększyłby
  `.exe` o kilkadziesiąt MB. Podgląd odświeża się po zmianie rozmiaru okna.
- Błędy w obsłudze zdarzeń okna trafiają do logu (aplikacja nie ma konsoli).
- Pole skali przyjmuje `50`, `1:50` i `1/50`.
- Przeciąganie plików do okna zapewnia `tkinterdnd2` (tkdnd 2.10 działa
  z Tk 9 z Pythona 3.15). Bez niego okno działa z wyborem pliku.
- `.exe` budowany jest przez PyInstaller jako jeden plik bez okna konsoli.
  Wykluczone są matplotlib, Pillow i narzędzia testowe (podgląd PNG nie jest
  dostępny w oknie). **Nie można wykluczyć `unittest`** — importuje go
  `pyparsing`, zależność ezdxf (bez niego `.exe` kończył się od razu).
- Błąd przy starcie aplikacji okienkowej (bez konsoli) jest zapisywany do
  `%TEMP%\PDF2DWG-blad.txt` i pokazywany w okienku komunikatu.

### Co faktycznie zwraca PyMuPDF 1.28.2 (rozpoznanie: `scripts/recon_pymupdf.py`)

Rozbieżności względem sekcji 6 SPEC i wynikające z nich decyzje:

1. `dashes` to **napis w składni PDF**, np. `"[ 6 3 ] 0"`; linia ciągła to
   `"[] 0"`, a ścieżka tylko wypełniana ma `None`. Wzór jest parsowany z napisu.
2. `layer` to `''` (pusty napis), gdy ścieżka nie należy do warstwy OCG.
3. Pola zależą od typu: dla `"f"` wartości `color`, `width`, `dashes`,
   `closePath`, `lineCap` są `None`; dla `"s"` — `fill`, `fill_opacity`,
   `even_odd` są `None`. Kod nie zakłada obecności wartości.
4. Element `("qu", quad)` ma wierzchołki w kolejności `ul, ur, ll, lr` (nie po
   obwodzie) — obwód budujemy jako `ul → ur → lr → ll`.
5. `closePath` jest zawodny: operator PDF `h` daje jawny odcinek zamykający,
   a `closePath` pozostaje `False`; okrąg z `draw_circle` to 4 krzywe z
   `closePath=False`. Podścieżka jest uznawana za zamkniętą, gdy
   `closePath` jest prawdą **albo** jej początek pokrywa się z końcem.
   Podścieżki wypełnień są zawsze traktowane jako zamknięte.
6. Zamknięte, osiowe czworokąty z czterech linii PyMuPDF sam zamienia na
   `("re", rect, orientacja)`, gdzie orientacja to `1` lub `-1`.
7. **Strony obrócone:** `get_drawings()` i `get_text()` zwracają współrzędne
   strony **nieobróconej** (np. `width=595, height=842`), choć `page.rect`
   ma wymiary po obrocie. Obrót stosujemy sami (jak `page.rotation_matrix`)
   do punktów, a jego część liniową do wektora `dir` tekstu.
8. Współrzędne są liczone od lewego górnego rogu **CropBox**, także przy
   MediaBox z niezerowym początkiem — nie trzeba ich korygować.
9. Tekst zgodny ze SPEC: span ma `text`, `origin`, `size`, `font`, `color`
   (int sRGB), a linia `dir` w układzie z osią Y w dół (`rotate=90` daje
   `dir=(0, -1)`, czyli 90° w DXF). Spany mają dodatkowo m.in. `alpha`,
   `bbox`, `ascender`, `descender`.
10. ezdxf nie ma funkcji „najbliższy kolor ACI dla RGB” — liczona własną
    funkcją na podstawie `ezdxf.colors.DXF_DEFAULT_COLORS`.

## Znane ograniczenia

- PDF to „spłaszczony” rysunek: nie ma w nim bloków, wymiarów asocjacyjnych
  ani informacji o tym, które linie tworzą jeden obiekt.
- Skalę rysunku musi podać użytkownik (`--scale`) — PDF jej nie przechowuje.
- Wzory kreskowania przychodzą jako setki lub tysiące pojedynczych linii.
- Fonty są zastępowane jednym fontem TTF (`arial.ttf`); położenie
  i wysokość tekstu są przybliżone, a szerokość napisu może się różnić od
  oryginału (nie jest dopasowywany współczynnik szerokości).
- Tekst zamieniony w PDF na krzywe przychodzi jako geometria (`SPLINE`,
  polilinie) — tak jest np. w plikach z `samples/`.
- Rozpoznawane są tylko łuki **okręgów**. Zaokrąglenia eliptyczne albo
  „gładkie” narożniki z programów graficznych (np. eksport macOS Quartz)
  zostają krzywymi `SPLINE` (albo polilinią przy `--curves polyline`).
- Ścieżki przycinające (clipping) są ignorowane — geometria ukryta w PDF
  przez maskę przycinania pojawi się w DXF.
- Obrazy rastrowe nie są przenoszone do DXF (raport o nich ostrzega).
- Tekst pionowy (`wmode = 1`) i tekst lustrzany nie są obsługiwane
  osobno — trafiają jako zwykły `TEXT` z kątem linii.
- Typy linii DXF nie mają przesunięcia fazy, więc początek wzoru kresek może
  się różnić od PDF.
- Skany wymagają wektoryzacji, której to narzędzie nie robi.
- DWG powstaje wyłącznie przez zewnętrzny ODA File Converter (instalowany
  osobno); bez niego dostępny jest tylko DXF.
- Polskie znaki przechodzą bez zmian w formatach Unicode — DXF i DWG od
  R2007 (domyślnie DXF R2010, DWG R2018). W starszych wersjach (`R2000`,
  `R2004`) litery spoza strony kodowej `ANSI_1252` są zapisywane jako
  sekwencje `\U+017C` (zarówno przez ezdxf, jak i przez ODA, który ignoruje
  `$DWGCODEPAGE` z pliku wejściowego). To standardowy zapis AutoCAD
  wyświetlany poprawnie m.in. przez AutoCAD i BricsCAD, ale prostsze
  programy mogą pokazać go dosłownie.
