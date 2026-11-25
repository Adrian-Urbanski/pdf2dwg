# PDF2DWG (pdf2dxf): dokumentacja techniczna

Ten dokument opisuje, jak działa program i co trzeba wiedzieć, żeby go
odtworzyć od zera. Zawiera wymagania, architekturę, wszystkie algorytmy
i stałe, interfejsy modułów, okno, budowanie `.exe`, testy oraz problemy
bibliotek odkryte podczas pracy.

Stan: wersja `0.1.0`, kod po commicie `6ccd140` (listopad 2026).
Instrukcja dla użytkownika jest w [README.md](README.md), a pierwotna
specyfikacja w [SPEC.md](SPEC.md).

---

## Spis treści

1. [Co robi program](#1-co-robi-program)
2. [Środowisko i zależności](#2-środowisko-i-zależności)
3. [Struktura projektu](#3-struktura-projektu)
4. [Architektura i przepływ danych](#4-architektura-i-przepływ-danych)
5. [Model pośredni (`model.py`)](#5-model-pośredni-modelpy)
6. [Ekstrakcja z PDF (`backends/`)](#6-ekstrakcja-z-pdf-backends)
7. [Transformacja współrzędnych (`transform.py`)](#7-transformacja-współrzędnych-transformpy)
8. [Postprocessing (`postprocess.py`)](#8-postprocessing-postprocesspy)
9. [Zapis DXF (`writer.py`)](#9-zapis-dxf-writerpy)
10. [Potok konwersji (`converter.py`)](#10-potok-konwersji-converterpy)
11. [Wiersz poleceń (`cli.py`)](#11-wiersz-poleceń-clipy)
12. [Podgląd PNG z DXF (`preview.py`)](#12-podgląd-png-z-dxf-previewpy)
13. [Konwersja do DWG (`dwg.py`)](#13-konwersja-do-dwg-dwgpy)
14. [Aplikacja okienkowa (`gui.py`)](#14-aplikacja-okienkowa-guipy)
15. [Budowanie `PDF2DWG.exe`](#15-budowanie-pdf2dwgexe)
16. [Testy](#16-testy)
17. [Odtworzenie programu krok po kroku](#17-odtworzenie-programu-krok-po-kroku)
18. [Pułapki bibliotek (ważne przy odtwarzaniu)](#18-pułapki-bibliotek-ważne-przy-odtwarzaniu)
19. [Znane ograniczenia](#19-znane-ograniczenia)
20. [Licencje](#20-licencje)

---

## 1. Co robi program

Program zamienia **wektorowe** rysunki PDF (eksporty z programów CAD
i graficznych) na pliki **DXF**. Opcjonalnie konwertuje je dalej do **DWG**
za pomocą zewnętrznego, darmowego programu ODA File Converter.

Program ma dwie formy:

| Forma | Uruchomienie | Wynik |
|---|---|---|
| Wiersz poleceń | `pdf2dxf rysunek.pdf [opcje]` albo `python -m pdf2dxf …` | DXF, opcjonalnie DWG i podgląd PNG |
| Okno (tkinter) | `PDF2DWG.exe` albo `pdf2dxf-gui` | DWG obok pliku PDF (opcjonalnie także DXF) |

**Kryterium poprawności:** DXF nakłada się wizualnie na oryginalny PDF,
a wymiary zmierzone w CAD (po podaniu skali rysunku) zgadzają się
z rysunkiem.

### Co jest przenoszone

| Element PDF | Encja DXF |
|---|---|
| otwarta ścieżka z 1 odcinka | `LINE` |
| ścieżka z wielu odcinków (otwarta lub zamknięta) | `LWPOLYLINE` |
| 4 krzywe Béziera tworzące okrąg | `CIRCLE` |
| krzywa Béziera przybliżająca łuk okręgu | `ARC` albo segment polilinii z wypukłością (bulge) |
| odcinki i łuki w jednej ścieżce (np. prostokąt z zaokrąglonymi rogami) | jedna `LWPOLYLINE` z bulge |
| pozostałe krzywe Béziera | `SPLINE` albo spłaszczona `LWPOLYLINE` (`--curves polyline`) |
| wypełnienie (`f`, `fs`) | `HATCH` SOLID (przy `fs` także obrys) |
| fragment tekstu (span) | `TEXT` (polskie znaki bez zmian) |
| kolor, grubość, linia przerywana, przezroczystość | true color + ACI, lineweight, własny typ linii, transparency |
| warstwy PDF (OCG) | warstwy DXF (opcja `--layers by-ocg`) |

Obsługiwane są pliki wielostronicowe, strony obrócone (`/Rotate`), skala
i jednostki.

### Czego program nie robi

- Nie wektoryzuje skanów. Wykrywa je, ostrzega i kończy się kodem 3.
- Nie przenosi obrazów rastrowych, ścieżek przycinających (clipping),
  bloków ani wymiarów asocjacyjnych.
- Nie zachowuje oryginalnych fontów: cały tekst dostaje jeden font
  `arial.ttf`.

---

## 2. Środowisko i zależności

Wersje, na których program został zbudowany i przetestowany:

| Składnik | Wersja | Rola |
|---|---|---|
| Windows 11 Pro (x64) | 10.0.26300 | system |
| Python | 3.15.2, 64-bit | wymagany ≥ 3.10 |
| PyMuPDF | 1.28.2 (`>=1.24,<2`) | ekstrakcja ścieżek i tekstu, render podglądu strony |
| ezdxf | 1.4.5 (`>=1.3`) | zapis DXF, `ezdxf.path`, `ezdxf.addons.odafc`, `ezdxf.addons.drawing` |
| matplotlib | 3.11.2 | opcjonalnie: podgląd PNG z DXF (`[preview]`) |
| numpy | 2.5.5 | zależność ezdxf i matplotlib, test wizualny |
| Tk (tkinter) | 9.0 | okno |
| tkinterdnd2 | 0.7.0 (zawiera tkdnd 2.10.3) | przeciąganie plików do okna |
| PyInstaller | 6.22.3 | budowanie `.exe` |
| Pillow | 13.0.0 | ikona `.exe`, test wizualny |
| pytest | 9.2.0 | testy |
| pymupdf-fonts | 1.0.5 | font Unicode (Noto Sans, `"notos"`) do testów z polskimi znakami |
| ODA File Converter | 27.10.0 | zewnętrzny program DXF → DWG, instalowany osobno |

Domyślna instalacja ODA:
`C:\Program Files\ODA\ODAFileConverter 27.10.0\ODAFileConverter.exe`.
Instalator pobiera się ze strony
<https://www.opendesign.com/guestfiles/oda_file_converter>.

**Dlaczego PyMuPDF < 2:** PyMuPDF 2.x wymaga `onnxruntime`, które nie ma
pakietów dla Pythona 3.15.

### `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "pdf2dxf"
version = "0.1.0"
description = "Konwerter wektorowych rysunków PDF do DXF (opcjonalnie DWG)"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "pymupdf>=1.24,<2",
    "ezdxf>=1.3",
]

[project.optional-dependencies]
preview = ["matplotlib>=3.7"]
gui = ["tkinterdnd2>=0.4"]
build = ["pyinstaller>=6", "tkinterdnd2>=0.4", "pillow"]
dev = ["pytest>=8", "pymupdf-fonts>=1.0", "matplotlib>=3.7", "tkinterdnd2>=0.4"]

[project.scripts]
pdf2dxf = "pdf2dxf.cli:main"

[project.gui-scripts]
pdf2dxf-gui = "pdf2dxf.gui:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
markers = ["slow: wolne testy (np. wizualne porównanie rastrów)"]
filterwarnings = ["ignore:'typing.ByteString':DeprecationWarning"]
```

Filtr ostrzeżeń ukrywa `DeprecationWarning`, który PyMuPDF 1.28 zgłasza na
Pythonie 3.15.

### Pliki gita

- `.gitignore`: `.venv/`, `__pycache__/`, `*.py[cod]`, `*.egg-info/`,
  `.pytest_cache/`, `build/`, `dist/`, `out/`, `samples/*.dxf`,
  `samples/*.dwg`, `samples/*.png`.
- `.gitattributes`: `* text=auto eol=lf`, `*.pdf binary`,
  `*.dxf text eol=crlf`, `*.png binary`.

---

## 3. Struktura projektu

```
G:\pdf to dwg\
├── pyproject.toml
├── README.md               instrukcja użytkownika + „Decyzje projektowe”
├── SPEC.md                 pierwotna specyfikacja
├── DOKUMENTACJA.md         ten dokument
├── samples\                przykładowe PDF-y użytkownika (wyniki ignorowane przez git)
├── dist\PDF2DWG.exe        zbudowana aplikacja (poza gitem)
├── scripts\
│   ├── recon_pymupdf.py    rozpoznanie: rzeczywista struktura danych PyMuPDF
│   ├── pdf2dwg_gui.py      punkt wejścia aplikacji okienkowej dla PyInstaller
│   └── build_exe.py        budowanie dist\PDF2DWG.exe
├── src\pdf2dxf\
│   ├── __init__.py         __version__ = "0.1.0"
│   ├── __main__.py         python -m pdf2dxf → cli.main()
│   ├── model.py            dataclasses modelu pośredniego
│   ├── backends\
│   │   ├── __init__.py     open_pdf(path) → PyMuPdfBackend
│   │   ├── base.py         ABC PdfBackend, PdfError
│   │   └── pymupdf_backend.py
│   ├── transform.py        PDF pt → jednostki DXF (obrót, odbicie Y, skala)
│   ├── postprocess.py      zaokrąglanie, duplikaty, łuki, --join, --merge-text
│   ├── writer.py           zapis DXF przez ezdxf
│   ├── converter.py        potok: strony → ekstrakcja → … → zapis → podgląd/DWG
│   ├── cli.py              argparse, raport, kody wyjścia
│   ├── preview.py          PNG z DXF (matplotlib, opcjonalne)
│   ├── dwg.py              DXF → DWG przez ODA File Converter
│   └── gui.py              okno tkinter
└── tests\                  pytest (207 przypadków)
```

Katalogiem głównym projektu jest katalog, w którym leży `SPEC.md`. W SPEC
narysowano podkatalog `pdf2dxf/`, ale nie został utworzony.

---

## 4. Architektura i przepływ danych

```
PDF
 │  backends/pymupdf_backend.py   page.get_drawings(), page.get_text("dict")
 ▼
PageData (space="pdf")            pt, początek w lewym górnym rogu CropBox, Y w dół,
 │                                strona NIEobrócona
 │  transform.py                  obrót strony → odbicie Y → × k → przesunięcie
 ▼
PageData (space="dxf")            jednostki rysunku, Y w górę, obrót zastosowany
 │  postprocess.py (+ merge_texts) zaokrąglenie, odcinki zerowe, duplikaty, łuki, --join
 ▼
writer.py (ezdxf)                 LINE / LWPOLYLINE / ARC / CIRCLE / SPLINE / HATCH / TEXT
 ▼
plik .dxf ──► [preview.py → .png]  ──► [dwg.py → ODA File Converter → .dwg]
```

### Zasady

1. **Separacja bibliotek.** Backend nie importuje ezdxf, a writer nie
   importuje PyMuPDF. Łączy je tylko model pośredni. Okno też nie importuje
   PyMuPDF: podgląd idzie przez `PdfBackend.render_png`. Dzięki temu backend
   PyMuPDF (licencja AGPL) można wymienić, np. na pypdfium2.
2. **Dwie przestrzenie współrzędnych** w jednym modelu, rozróżniane polem
   `PageData.space`:
   - `"pdf"`: wynik backendu (pt, Y w dół, strona nieobrócona);
   - `"dxf"`: wynik transformacji (jednostki rysunku, Y w górę, obrót
     zastosowany).

   Postprocessing i writer odrzucają stronę w złej przestrzeni
   (`ValueError`).
3. **Układ współrzędnych zmienia się tylko w `transform.py`.**
4. **Grubość linii i wzory kresek zostają w pt** w obu przestrzeniach.
   Writer przelicza je sam: grubość bez skali, kreski przez
   `PageData.unit_scale` (= `k`).
5. **`converter.py` jest wspólny dla CLI i okna.** CLI tylko parsuje
   argumenty i drukuje raport. Okno wywołuje `convert()` i
   `format_report()`.

### Zależności między modułami

```
cli ──► converter ──► backends, transform, postprocess, writer
            └──(import leniwy)──► preview, dwg
gui ──► converter, cli.format_report, dwg (find_converter, ODA_URL, DWG_VERSIONS),
        backends.open_pdf (podgląd)
writer ──► model, transform (UNIT_FACTORS, INSUNITS)
```

`preview` i `dwg` są importowane dopiero wtedy, gdy są potrzebne. Dzięki
temu brak matplotlib nie psuje konwersji, a `.exe` nie musi zawierać
matplotlib.

---

## 5. Model pośredni (`model.py`)

Wszystkie klasy to dataclasses. `Point = tuple[float, float]`,
`RGB = tuple[float, float, float]` (składowe 0–1).

| Klasa | Pola | Uwagi |
|---|---|---|
| `DashPattern` (frozen) | `lengths: tuple[float, ...]`, `phase=0.0` | długości w pt: kreska, przerwa, … |
| `Style` (frozen, hashowalny) | `stroke_color: RGB\|None=(0,0,0)`, `fill_color: RGB\|None=None`, `line_width=1.0` (pt), `dashes: DashPattern\|None`, `layer: str\|None` (OCG), `stroke_opacity=1.0`, `fill_opacity=1.0` | służy jako klucz słownika w deduplikacji i `--join` |
| `LineSeg` (frozen) | `p1`, `p2` | `start`, `end`, `reversed()` |
| `CubicSeg` (frozen) | `p1`, `c1`, `c2`, `p2` | `reversed()` = `(p2, c2, c1, p1)` |
| `ArcSeg` (frozen) | `p1`, `p2`, `center`, `sweep` (°) | tylko w przestrzeni DXF; `sweep > 0` oznacza obieg przeciwny do wskazówek zegara (Y w górę) |
| `SubPath` | `segments: list[Segment]`, `closed=False` | `start`, `end`, `points()` (węzły bez punktów kontrolnych) |
| `Shape` | `subpaths`, `style`, `stroked=True`, `filled=False`, `even_odd=False` | jedna ścieżka PDF |
| `TextItem` | `text`, `origin`, `size`, `angle=0`, `font=""`, `color=(0,0,0)`, `layer=None`, `opacity=1`, `width=0` | patrz niżej |
| `PageData` | `index` (od 0), `width`, `height`, `rotation=0`, `shapes`, `texts`, `image_count=0`, `image_coverage=0.0`, `warnings`, `space="pdf"`, `unit_scale=1.0` | `number` = `index + 1` |

`TextItem` w przestrzeni PDF: `size` to rozmiar fontu w pt, a `angle` to
`atan2(dir.y, dir.x)` w stopniach, w układzie z osią Y w dół. W przestrzeni
DXF: `size` jest w jednostkach rysunku, a `angle` to obrót encji `TEXT`
(przeciwnie do wskazówek zegara). `width` to długość napisu wzdłuż linii
bazowej (0 = nieznana).

### Matematyka `ArcSeg`

- `radius = |p1 − center|`
- `bulge = tan(sweep_rad / 4)`: wypukłość segmentu `LWPOLYLINE`.
- `start_angle = atan2(p1 − center)` w stopniach.
- `reversed()` = `ArcSeg(p2, p1, center, −sweep)`.
- `split()`: dwa łuki po `sweep/2`. Punkt środkowy leży pod kątem
  `start_angle + sweep/2`.
- `to_cubics()`: przybliżenie krzywymi Béziera, po jednej na każde
  rozpoczęte 90°. `n = max(1, ceil(|sweep| / 90° − 1e-9))`,
  `step = sweep / n`, `κ = 4/3 · tan(step / 4)`. Dla kątów `t0`, `t1` na
  końcach kawałka:
  ```
  c1 = (cx + r(cos t0 − κ sin t0),  cy + r(sin t0 + κ cos t0))
  c2 = (cx + r(cos t1 + κ sin t1),  cy + r(sin t1 − κ cos t1))
  ```
  Ostatni punkt końcowy to dokładnie `p2`, żeby nie powstał błąd
  zaokrąglenia.

---

## 6. Ekstrakcja z PDF (`backends/`)

### 6.1 Interfejs `PdfBackend` (`backends/base.py`)

```python
class PdfError(Exception): ...          # nie da się otworzyć/odczytać PDF

class PdfBackend(ABC):
    def __init__(self, path: Path)       # rzuca PdfError
    page_count: int                      # property
    def extract_page(self, index, *, with_text=True) -> PageData   # przestrzeń "pdf"
    def close(self)
    def render_png(self, index, max_width, max_height) -> bytes    # domyślnie NotImplementedError
    # obsługa with (__enter__/__exit__ → close)
```

`backends/__init__.py`: `open_pdf(path)` zwraca `PyMuPdfBackend(Path(path))`.
Import PyMuPDF jest leniwy, wewnątrz funkcji.

### 6.2 Co naprawdę zwraca PyMuPDF 1.28.2

Sprawdzone skryptem `scripts/recon_pymupdf.py`. Skrypt generuje testowy PDF
i wypisuje wyniki `page.get_drawings()` i `page.get_text("dict")`. PDF
zawiera: linię, prostokąt, okrąg, krzywą Béziera, tekst
„Zażółć gęślą jaźń”, linię przerywaną, wypełnienia, OCG, even-odd, stronę
obróconą i stronę z obrazem.

Opis w SPEC (sekcja 6) różni się od rzeczywistości w tych punktach:

1. `dashes` to **napis w składni PDF**, np. `"[ 6 3 ] 0"`. Linia ciągła ma
   `"[] 0"`, a ścieżka tylko wypełniana ma `None`.
2. `layer` to `""` (pusty napis), gdy ścieżka nie należy do warstwy OCG.
3. Obecność wartości zależy od typu ścieżki. Dla `"f"` pola `color`,
   `width`, `dashes`, `closePath` i `lineCap` są `None`. Dla `"s"` pola
   `fill`, `fill_opacity` i `even_odd` są `None`.
4. `("qu", quad)`: wierzchołki są w kolejności `ul, ur, ll, lr`, a nie po
   obwodzie.
5. `closePath` jest zawodny. Operator PDF `h` daje jawny odcinek
   zamykający, a `closePath` pozostaje `False`. Okrąg z `draw_circle` to
   4 krzywe z `closePath=False`.
6. Zamknięte, osiowe czworokąty z 4 linii PyMuPDF sam zamienia na
   `("re", rect, orientacja)`, gdzie orientacja to `1` lub `-1`.
   Orientacja `1` oznacza obieg przeciwny do wskazówek zegara **na
   ekranie**, jak operator PDF `re`.
7. **Strony obrócone:** `get_drawings()` i `get_text()` zwracają
   współrzędne strony **nieobróconej**, mimo że `page.rect` ma wymiary po
   obrocie.
8. Współrzędne są liczone od lewego górnego rogu **CropBox**, także przy
   MediaBox z niezerowym początkiem.
9. Span tekstu ma `text`, `origin`, `size`, `font`, `color` (int sRGB
   `0xRRGGBB`), `alpha`, `bbox`, `ascender`, `descender` i `char_flags`.
   Linia ma `dir` w układzie z osią Y w dół.
10. ezdxf nie ma funkcji „najbliższy ACI dla RGB”, więc program ma własną.

### 6.3 `PyMuPdfBackend`

**Otwieranie:** `pymupdf.open(path)`. Każdy wyjątek zamienia się na
`PdfError("nie można otworzyć PDF …")`. Gdy `not doc.is_pdf`, błąd to
„plik nie jest dokumentem PDF”. Gdy `doc.needs_pass`, błąd to „PDF jest
zabezpieczony hasłem”.

**`extract_page(index, with_text)`:**

1. `PageData(index, width=cropbox.width, height=cropbox.height, rotation=page.rotation % 360)`.
2. Dla każdego `d` w `page.get_drawings()`: `drawing_to_shape(d)`, a jeśli
   wynik nie jest `None`, kształt trafia na stronę.
3. Jeśli `with_text`: `extract_texts(page)`. Program dodaje ostrzeżenia
   „pominięto N niewidocznych fragmentów tekstu (np. warstwa OCR)”
   i „N fragmentów tekstu bez mapowania Unicode (znaki „�”)”.
4. `image_count, image_coverage = _image_stats(page, width, height)`.

**`render_png(index, max_w, max_h)`** (podgląd w oknie): bierze
`rect = page.rect` (wymiary **po** obrocie) i liczy
`zoom = max(0.01, min(max_w/rect.width, max_h/rect.height))`. Potem
`page.get_pixmap(matrix=Matrix(zoom, zoom), alpha=False).tobytes("png")`.

### 6.4 `drawing_to_shape(d)`

| Pole modelu | Źródło |
|---|---|
| `stroked` / `filled` | `"s" in d["type"]` / `"f" in d["type"]`; bez żadnego z nich → `None` |
| `subpaths` | `items_to_subpaths(d["items"], bool(d["closePath"]))`; pusta lista → `None` |
| `stroke_color` | `to_rgb(d["color"])`, gdy stroked, inaczej `None` |
| `fill_color` | `to_rgb(d["fill"])`, gdy filled, inaczej `None` |
| `line_width` | `d["width"]`, a `None` → `0.0` |
| `dashes` | `parse_dashes(d["dashes"])`, gdy stroked |
| `layer` | `d["layer"] or None` |
| opacity | `stroke_opacity` / `fill_opacity`, a `None` → `1.0` |
| `even_odd` | `bool(d["even_odd"])` |

### 6.5 `items_to_subpaths(items, close_path)`: podział na podścieżki

Stała `JOIN_TOL = 1e-3` pt. Dwa punkty są „równe”, gdy |Δx| ≤ tol
i |Δy| ≤ tol.

```
wynik = []; bieżąca = []
dla każdego elementu:
    "re" / "qu"  → zamknij bieżącą; dodaj osobną ZAMKNIĘTĄ podścieżkę z 4 odcinków
    "l"          → LineSeg(p1, p2)
    "c"          → CubicSeg(p1, p2, p3, p4)
    inne         → pomiń
    jeśli bieżąca niepusta i początek segmentu ≠ koniec ostatniego → zamknij bieżącą
    dodaj segment do bieżącej
zamknij bieżącą

zamknięcie podścieżki:
    closed = (nie jest pojedynczym LineSeg) i start ≈ koniec
    jeśli closed → koniec ostatniego segmentu ustaw DOKŁADNIE na start

jeśli close_path i ostatnia podścieżka nie jest zamknięta:
    jeśli koniec ≠ start → dodaj LineSeg(koniec, start)
    closed = True
```

Podścieżka jest więc zamknięta, gdy `closePath` jest prawdą **albo** gdy
jej koniec pokrywa się z początkiem. Dociągnięcie końca sprawia, że w DXF
nie powstają zdublowane wierzchołki.

**Wierzchołki `re`/`qu`** (kolejność ma znaczenie dla reguły wypełniania
nonzero):

- `re`, orientacja 1: `(x0,y1) → (x1,y1) → (x1,y0) → (x0,y0)`, czyli lewy
  dolny → prawy dolny → prawy górny → lewy górny w układzie z osią Y
  w dół.
- `re`, orientacja −1: ten sam start, reszta w odwrotnej kolejności.
- `qu`: `ul → ur → lr → ll`.

### 6.6 Styl

**`parse_dashes(value)`:** wyrażenie regularne
`\[\s*([^\]]*)\]\s*([-+0-9.eE]*)`. Długości to wartości bezwzględne
(przecinek też działa jako separator), faza jest liczbą. Zwraca `None` dla
`None`, `""`, `"[] 0"`, samych zer albo błędu parsowania. Nieparzystą
liczbę wartości podwaja, jak w PDF (`[3]` → `[3 3]`).

**`to_rgb(color)`:** obcina składowe do 0–1. Działa dla:

- 1 składowej (szarość): `(g, g, g)`;
- 3 składowych (RGB): bez zmian;
- 4 składowych (CMYK): `((1−c)(1−k), (1−m)(1−k), (1−y)(1−k))`.

Dla innej liczby składowych zwraca `None`.

### 6.7 Tekst: `extract_texts(page)`

- Flagi: `pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES`.
- Pomija bloki o `type != 0` (obrazy).
- Dla linii: `angle = degrees(atan2(dir.y, dir.x))`.
- Dla spanu:
  - `clean_text`: tabulator zamienia na spację, usuwa pozostałe znaki
    o kodzie < 32;
  - pomija spany z samych białych znaków;
  - **niewidoczny**, gdy `alpha == 0` albo gdy `char_flags` istnieje i nie
    ma bitów `16 | 32` (FILLED | STROKED, tryb renderowania 3, typowy dla
    warstwy OCR skanów). Taki span jest pomijany i liczony do ostrzeżenia;
  - jeśli tekst zawiera `U+FFFD`, span trafia do DXF, ale jest liczony do
    ostrzeżenia;
  - `TextItem(text, origin=span["origin"], size, angle, font, color=int_to_rgb(color), opacity=alpha/255, width=_span_advance(...))`.

**`_span_advance`:** odtwarza długość napisu z prostokąta otaczającego.
Dla tekstu obróconego bbox jest obwiednią osiową:
`w_bb = W·|cos| + H·|sin|` i `h_bb = W·|sin| + H·|cos|`. Wysokość to
`H = size · (ascender − descender)`, `c = |dir.x|`, `s = |dir.y|`. Stąd:

```
c ≥ s:  W = (w_bb − H·s) / c
c < s:  W = (h_bb − H·c) / s        (wynik ≥ 0)
```

### 6.8 Obrazy: `_image_stats`

Liczba obrazów to `len(page.get_image_info())`. Pokrycie to suma pól
bboxów przyciętych do prostokąta `(0, 0, w, h)`, podzielona przez pole
strony. Nakładanie się nie jest odejmowane, a wynik jest obcięty do 1.

---

## 7. Transformacja współrzędnych (`transform.py`)

### Jednostki

| `--units` | `UNIT_FACTORS` (jednostek na 1 pt) | `$INSUNITS` |
|---|---|---|
| `mm` (domyślne) | 25.4 / 72 | 4 |
| `cm` | 2.54 / 72 | 5 |
| `m` | 0.0254 / 72 | 6 |
| `in` | 1 / 72 | 1 |
| `pt` | 1 | 0 (bez jednostek) |

`k = UNIT_FACTORS[units] × scale`. `--scale N` oznacza rysunek w skali
1:N, więc współrzędne są mnożone przez N i w DXF są wymiary rzeczywiste.

### Przekształcenie afiniczne (konwencja PyMuPDF)

```
x' = a·x + c·y + e
y' = b·x + d·y + f
```

`A.then(B)` oznacza „najpierw A, potem B”:

```
a = A.a·B.a + A.b·B.c      b = A.a·B.b + A.b·B.d
c = A.c·B.a + A.d·B.c      d = A.c·B.b + A.d·B.d
e = A.e·B.a + A.f·B.c + B.e
f = A.e·B.b + A.f·B.d + B.f
```

### Obrót strony

Obrót działa jak `page.rotation_matrix`, dla strony nieobróconej
`W × H` pt. Obrót musi być wielokrotnością 90°, inaczej program rzuca
`ValueError`.

| `/Rotate` | Affine(a, b, c, d, e, f) | wynik | wymiary po obrocie |
|---|---|---|---|
| 0 | (1, 0, 0, 1, 0, 0) | x, y | W × H |
| 90 | (0, 1, −1, 0, H, 0) | x' = H − y, y' = x | H × W |
| 180 | (−1, 0, 0, −1, W, H) | x' = W − x, y' = H − y | W × H |
| 270 | (0, −1, 1, 0, 0, W) | x' = y, y' = W − x | H × W |

### Pełna transformacja: `make_transform(W, H, rotation, units, scale, offset)`

```
rot  = rotation_matrix(W, H, rotation)
w, h = rotated_size(W, H, rotation)
flip = Affine(k, 0, 0, −k, ox, h·k + oy)       # x = x'·k + ox,  y = (h − y')·k + oy
matrix = rot.then(flip)
Transform(matrix, k, width = w·k, height = h·k)
```

Metody `Transform`:

- `point(p)`;
- `vector(v)`: tylko część liniowa;
- `length(v) = v·k`;
- `angle(pdf_deg)`: wektor `(cos, sin)` przepuszczony przez część liniową,
  potem `atan2`;
- `mirrors`: `det < 0`, co przy odbiciu Y jest zawsze prawdą.

### `transform_page(page, tr)`

Zwraca kopię strony z `space="dxf"`, `rotation=0`, `unit_scale=k` i
wymiarami po obrocie. Każdy segment przechodzi przez `tr.point`. Łuk
dostaje `sweep` z przeciwnym znakiem, gdy `tr.mirrors`. Tekst:

- `origin` przez `point`;
- `size` i `width` przez `length`;
- `angle` przez `tr.angle`.

Dla tekstu z `dir=(0,−1)` (`rotate=90` w PyMuPDF) wychodzi 90° w DXF.

---

## 8. Postprocessing (`postprocess.py`)

Działa na stronie w przestrzeni DXF. Wszystkie tolerancje są wyrażone
**w pt na arkuszu** i mnożone przez `k = page.unit_scale`, więc wynik nie
zależy od `--units` ani `--scale`.

| Stała | Wartość | Znaczenie |
|---|---|---|
| `ROUND_DIGITS` | 6 | zaokrąglenie współrzędnych (cyfry po przecinku, jednostki DXF) |
| `ZERO_LENGTH_TOL_PT` | 0.005 | segmenty ≤ tej długości to szum numeryczny (≈ 0.002 mm) |
| `FULL_CIRCLE_SLACK` | 0.5° | zapas przy łączeniu łuków w pełny okrąg |
| `DEDUP_TOL_PT` | 0.01 | siatka porównywania przy deduplikacji i `--join` |
| `ARC_ABS_TOL_PT` | 0.005 | bezwzględna tolerancja wykrywania łuków |
| `ARC_REL_TOL` | 1e-3 | względna tolerancja łuków (ułamek promienia) |
| `ARC_MAX_SWEEP` | 91° | największy łuk rozpoznawany z jednej krzywej Béziera |
| `MERGE_MAX_GAP` | 0.5 | największa przerwa przy łączeniu tekstu (× rozmiar fontu) |
| `MERGE_SPACE_GAP` | 0.15 | przerwa, od której wstawiana jest spacja (× rozmiar fontu) |

Kolejność kroków w `postprocess_page(page, PostprocessOptions(detect_arcs=True, join=False))`:

```
round_shape → remove_zero_length(0.005·k) → deduplicate(0.01·k)
→ [detect_arcs(0.005·k)] → [join_subpaths(0.01·k)]
```

Funkcja zwraca `(nowa strona, PostprocessStats(zero_length_removed, duplicates_removed, arcs_detected, joined))`.
Tekstu nie zmienia (`merge_texts` wywołuje potok osobno).

### 8.1 Zaokrąglanie

`round(v, 6) + 0.0` dla każdego punktu, także punktów kontrolnych
i środków łuków. Dodanie `+ 0.0` usuwa `-0.0`.

### 8.2 Odcinki zerowej długości: `remove_zero_length`

Segment jest „zerowy”, gdy:

- `LineSeg`: `|p2 − p1| ≤ tol`;
- `CubicSeg`: c1, c2 i p2 leżą ≤ tol od p1;
- `ArcSeg`: `|p2 − p1| ≤ tol` i `|sweep| < 1°`.

Po usunięciu segmentów `_reconnect` dociąga początek każdego segmentu do
końca poprzedniego, a w zamkniętej podścieżce także koniec ostatniego do
startu. Podścieżka zostaje zamknięta tylko wtedy, gdy ma > 1 segment.
Puste podścieżki i kształty znikają.

Ten krok jest konieczny dla eksportów macOS Quartz. Zapisują one
współrzędne w float32, więc po operatorze `h` zostaje mikroskopijny odcinek
zamykający, który blokowałby rozpoznanie okręgu.

### 8.3 Deduplikacja: `deduplicate(shapes, grid)`

Punkty są kwantowane do siatki: `q(p) = (round(x/grid), round(y/grid))`.

Klucz segmentu:

- `("L", q(p1), q(p2))`;
- `("C", q(p1), q(c1), q(c2), q(p2))`;
- `("A", q(p1), q(p2), q(center), round(sweep, 3))`.

Klucz podścieżki nie zależy od kierunku:

- otwarta: `min(krotka_w_przód, krotka_wstecz)`;
- zamknięta: także od punktu startu, czyli minimum z obrotów listy kluczy
  do najmniejszego elementu, w obu kierunkach.

Klucz stylu to `(Style, stroked, filled, even_odd)`. Usuwane są tylko
duplikaty o identycznym stylu.

1. **Kształty z wypełnieniem** są porównywane w całości: klucz stylu plus
   posortowane klucze podścieżek.
2. **Kształty tylko z obrysem:** usuwana jest każda podścieżka, której
   klucz już wystąpił.
3. **Drugie przejście:** zbiór krawędzi (klucz segmentu niezależny od
   kierunku) ze wszystkich wielosegmentowych podścieżek obrysowych. Usuwa
   pojedyncze, otwarte odcinki pokrywające się z bokiem takiej polilinii
   o tym samym stylu.

### 8.4 Łuki i okręgi

**`cubic_to_arc(seg, abs_tol)`:** sprawdza, czy pojedyncza krzywa Béziera
jest łukiem okręgu.

```
p0, p3 = końce;  t0 = c1 − p0,  t1 = p3 − c2;  l0 = |t0|, l1 = |t1|
odrzuć, gdy l0, l1 lub |p3 − p0| ≤ abs_tol
normalne n0 = (−t0.y, t0.x), n1 = (−t1.y, t1.x);  det = n0 × n1
odrzuć, gdy |det| ≤ 1e-9·l0·l1          (styczne równoległe: prosta albo półokrąg)
środek = p0 + a·n0,  a = ((p3 − p0) × n1) / det     (przecięcie normalnych)
r0 = |p0 − środek|, r1 = |p3 − środek|, r = (r0 + r1)/2
tol = max(1e-3·r, abs_tol)
odrzuć, gdy |r0 − r1| > tol
kierunek: ccw = (v0 × t0 > 0); musi być równy (v1 × t1 > 0)
sweep = atan2(v0 × v1, v0 · v1), skorygowany o ±2π do znaku ccw
odrzuć, gdy |sweep| > 91°
dla t = ¼, ½, ¾: odrzuć, gdy | |B(t) − środek| − r | > tol
ramię oczekiwane h = 4/3 · tan(|sweep|/4) · r
odrzuć, gdy |l0 − h| lub |l1 − h| > max(0.05·h, tol)
wynik: ArcSeg(p0, p3, środek, degrees(sweep))
```

Elipsy i „gładkie” zaokrąglenia z programów graficznych nie przechodzą
tego testu i zostają krzywymi.

**`detect_arcs`:** działa tylko na podścieżkach zawierających `CubicSeg`.
Zamienia rozpoznane krzywe na `ArcSeg`, a potem łączy łuki funkcją
`merge_arcs` z tolerancją
`r_tol = max(abs_tol, 1e-3 · najmniejszy promień w podścieżce)`.

**`merge_arcs(segments, closed, tol)`:** dwa kolejne łuki można połączyć,
gdy:

- mają ten sam kierunek;
- środki są ≤ tol od siebie, a promienie różnią się o ≤ tol;
- `|sweep_a + sweep_b| ≤ 360° + 0.5°`.

W zamkniętej podścieżce, jeśli ostatni i pierwszy segment dają się
połączyć, końcowa seria łuków jest przenoszona na początek. Dzięki temu
punkt startu nie rozcina łuku. Potem następuje liniowe łączenie:
`ArcSeg(prev.p1, seg.p2, prev.center, prev.sweep + seg.sweep)`.

Cztery ćwiartki okręgu dają więc jeden łuk 360°, który writer zapisze jako
`CIRCLE`.

### 8.5 Łączenie odcinków: `join_subpaths` (`--join`)

- Dotyczy tylko kształtów z obrysem i bez wypełnienia. Zamknięte
  podścieżki zostają w swoich kształtach.
- Otwarte podścieżki trafiają do puli według `Style`. Kolejność pul
  odpowiada kolejności pierwszego wystąpienia stylu.
- `_chain(pula, grid)`: mapa „węzeł → indeksy podścieżek” dla obu końców.
  Łączenie przechodzi **tylko przez węzły z dokładnie dwoma końcami**, bo
  przy rozgałęzieniach (T, X) wynik byłby przypadkowy.
  1. Łańcuch rośnie w przód od końca, potem wstecz od początku.
  2. Kawałek jest odwracany, jeśli trzeba, a stykające się końce są
     dociągane dokładnie do siebie.
  3. Łańcuch z > 1 elementu, którego koniec trafia w początek, staje się
     zamknięty.
- Połączone podścieżki trafiają do nowych kształtów **na końcu** listy
  (zmienia się kolejność rysowania). Statystyka `joined` to liczba
  podścieżek wchłoniętych w dłuższe.

### 8.6 Łączenie tekstu: `merge_texts` (`--merge-text`)

Działa sekwencyjnie: każdy fragment próbuje dołączyć do poprzedniego
wyniku. Dwa fragmenty `a` i `b` łączą się, gdy spełnione są wszystkie
warunki:

- równe `font`, `color`, `opacity` i `layer`;
- `a.size > 0`, `a.width > 0`, rozmiary równe (względnie do 1e-6);
- kąty różnią się o ≤ 0.5° (modulo 360°);
- rzut `b.origin − a.origin` na kierunek `a`: `along` (wzdłuż)
  i `across` (w poprzek), przy czym `|across| ≤ 0.1·size`;
- `gap = along − a.width` mieści się w `[−0.1·size, 0.5·size]`.

Spacja jest wstawiana, gdy `gap > 0.15·size` i żaden z fragmentów nie ma
już spacji na styku. Nowa szerokość to `along + b.width`.

Funkcja działa w przestrzeni DXF, przed postprocessingiem.

---

## 9. Zapis DXF (`writer.py`)

### 9.1 Opcje i dokument

`WriterOptions(units="mm", dxf_version="R2010", curves="spline", flatten_tol_mm=0.01, layers="by-color", fills="hatch", text_height_factor=0.7)`.

- Dokument: `ezdxf.new(dxf_version, setup=False)`.
- Nagłówek:
  - `$INSUNITS` z tabeli jednostek;
  - `$MEASUREMENT` = 0 dla `in`, 1 dla pozostałych;
  - `$LWDISPLAY` = 1, żeby CAD od razu pokazywał grubości.
- Tolerancja spłaszczania w jednostkach DXF: `tol = flatten_tol_mm / (25.4/72) × k`.
  Oznacza to mm na arkuszu, przed skalą.

### 9.2 Kolory

- `is_black`: wszystkie składowe ≤ 0.05. Toleruje „głęboką czerń”
  z konwersji CMYK.
- `color_attribs(color)`:
  - czarny lub `None` → `{"color": 7}`, **bez** true color. True color ma
    pierwszeństwo nad ACI, więc czarne linie zniknęłyby na czarnym tle CAD;
  - inne kolory → `{"color": nearest_aci(rgb255), "true_color": rgb2int(rgb255)}`.
- `nearest_aci(rgb)`: najmniejsza odległość euklidesowa RGB wśród ACI
  1–255 z `ezdxf.colors.DXF_DEFAULT_COLORS`, z `lru_cache`.
- Kolor jest ustawiany jawnie na encji, nie BYLAYER.

### 9.3 Warstwy: `layer_for(color, ocg)`

| `--layers` | Nazwa | Kolor warstwy |
|---|---|---|
| `by-color` (domyślnie) | `PDF_RRGGBB` z koloru elementu (`None` → `PDF_000000`) | odpowiada nazwie |
| `by-ocg` | nazwa OCG po oczyszczeniu; bez OCG działa jak `by-color` | ACI 7 |
| `single` | `PDF` | ACI 7 |

Czyszczenie nazwy: znaki ``<>/\":;?*|=` `` i znaki sterujące zamieniane są
na `_`, potem `strip()`, maksymalnie 255 znaków, a pusta nazwa daje `PDF`.
Warstwa powstaje przy pierwszym użyciu. Kolor elementu to: kolor obrysu
dla obrysu, kolor wypełnienia dla wypełnienia, kolor tekstu dla tekstu.

### 9.4 Grubość, kreski, przezroczystość

- **Lineweight:** `target = width_pt × 25.4/72 × 100` (setne mm). Wybierana
  jest najbliższa wartość z `VALID_DXF_LINEWEIGHTS`, a przy remisie
  mniejsza:
  `(0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211)`.
  Grubość **nie** podlega skali. Grubość 0 z PDF daje lineweight 0.
- **Typ linii** (`linetype_for(dashes, k)`):
  - długości × k, zaokrąglone do 9 cyfr, służą jako klucz cache;
  - nazwa `PDF_DASH_1`, `PDF_DASH_2`, …;
  - wzór `[suma, kreska, −przerwa, kreska, −przerwa, …]`;
  - opis `PDF [6 3] pt`.

  Kreski **skalują się** z geometrią. Faza wzoru jest pomijana, bo typy
  linii DXF jej nie mają. Typ linii jest przypisywany tylko wtedy, gdy
  `suma × k > 0`.
- **Przezroczystość:** `float2transparency(1 − opacity)`, tylko gdy
  opacity < 1. Dotyczy obrysów, wypełnień i tekstu.

### 9.5 Wybór encji dla podścieżki: `_add_curve(sp, attribs, tol)`

```
1. same LineSeg             → _add_lines(points, closed)
2. same LineSeg + ArcSeg:
     jeden ArcSeg:  |sweep| ≈ 360° (±0.5°)     → CIRCLE(center, r)
                    otwarty                    → ARC
     pozostałe                                 → LWPOLYLINE z bulge (format "xyb")
3. curves == "polyline"     → flatten(sp, tol) → _add_lines
4. curves == "spline"       → to_bsplines_and_vertices(to_ezdxf_path(start_at_curve(sp)))
                               BSpline        → add_spline() + apply_construction_tool(bspline)
                               lista punktów  → _add_lines(…, closed=False)
```

Krok 2 jest przed krokiem 3, więc **wykryty okrąg zostaje `CIRCLE` także
w trybie polilinii**. Spłaszczony okrąg wymaga
`--curves polyline --no-detect-arcs`.

**`_add_lines(pts, closed)`:** w zamkniętej liście (> 2 punkty) usuwany
jest ostatni punkt, jeśli równa się pierwszemu (tolerancja 1e-9). Dwa
punkty i brak zamknięcia dają `LINE`. W pozostałych przypadkach powstaje
`LWPOLYLINE(format="xy", close=closed)`.

**`_add_arc`:** ARC w DXF biegnie zawsze przeciwnie do wskazówek zegara.
Gdy `sweep > 0`, kąty to (start, koniec), w przeciwnym razie (koniec,
start). Kąty są normalizowane do [0, 360).

**`to_ezdxf_path(sp)`:**

- `LineSeg` → `line_to(p2)`;
- `CubicSeg` → `curve4_to(p2, c1, c2)`;
- `ArcSeg` → `to_cubics()`, potem `curve4_to`;
- `close()`, gdy podścieżka jest zamknięta.

**`bulge_points(sp)`:** łuki > 180° są dzielone na połowy, bo bulge
pełnego okręgu byłby nieskończony. Wierzchołek ma postać
`(x, y, bulge segmentu zaczynającego się w nim)`. Otwarta podścieżka
dostaje dodatkowo punkt końcowy z bulge 0.

**`start_at_curve(sp)`:** w zamkniętej podścieżce, która zaczyna się
i kończy odcinkiem, punkt startu przesuwa się na pierwszą krzywą. Dzięki
temu odcinki sprzed i zza punktu startu tworzą jedną polilinię.

**`flatten(sp, tol)`:** `to_ezdxf_path(sp).flattening(distance=tol)`, potem
usunięcie kolejnych powtórzonych punktów.

`to_bsplines_and_vertices` z `ezdxf.path` rozdziela ciągi krzywych na
`SPLINE` (dzieląc w narożnikach bez ciągłości G1) i ciągi odcinków na
listy punktów. Działa jak `render_splines_and_polylines` z SPEC, ale bez
3D `POLYLINE`, które tamta funkcja tworzy dla odcinków.

### 9.6 Kształt: `_add_shape(shape, page, tol)`

```
jeśli filled i _is_background(shape, page) → pomiń cały kształt
fills == "hatch"   i filled                  → _add_hatch
fills == "outline" i filled i NIE stroked    → każda podścieżka jako zamknięty kontur w kolorze wypełnienia
fills == "ignore"                            → wypełnienie pominięte
jeśli stroked → każda podścieżka przez _add_curve z atrybutami obrysu
```

`_is_background`: wypełnienie białe (składowe ≥ 0.98), obrys brak albo
także biały, a bbox kształtu ≥ 90 % pola strony.

### 9.7 Kreskowanie: `_add_hatch`

1. Każda podścieżka jest spłaszczana jako zamknięta, a powtórzony ostatni
   punkt usuwany. Zostaje, gdy ma ≥ 3 punkty i `|pole| > tol²`.
2. Jeśli podścieżka ma same odcinki i łuki, kontur jest zapisywany
   **dokładnie**, z wierzchołkami bulge.
3. `msp.add_hatch(color=ACI, dxfattribs=…)`, potem
   `set_solid_fill(color, style=0, rgb=true_color)`. Styl 0 („normal”)
   oznacza wyspy na przemian, czyli regułę even-odd.
4. `hatch_boundaries(polys, even_odd)` wybiera kontury i oznacza
   zewnętrzne:
   - punkt próbny konturu to środek jego pierwszej krawędzi;
   - `containers[i]` to kontury zawierające punkt próbny `i` (test
     parzystości przecięć promienia);
   - reguła **even-odd**: zostają wszystkie kontury;
   - reguła **nonzero**: `znak = +1`, gdy pole ze znakiem ≥ 0 (przeciwnie
     do wskazówek zegara), inaczej −1. `zewn = Σ znak(kontenerów)`.
     Kontur zostaje, gdy `(zewn ≠ 0) ≠ (zewn + znak_i ≠ 0)`, czyli gdy na
     nim zmienia się stan wypełnienia. Wewnętrzny kontur o tym samym
     kierunku obiegu nie robi więc dziury;
   - kontur jest „zewnętrzny”, gdy nie zawiera go żaden z zachowanych
     konturów.
5. `hatch.paths.add_polyline_path(vertices, is_closed=True, flags=1 dla zewnętrznego, 0 dla pozostałych)`.

### 9.8 Tekst

- Styl `PDF_TEXT` z fontem `arial.ttf`, tworzony raz.
- `TEXT`:
  - punkt wstawienia to `origin` (lewy koniec linii bazowej);
  - `height = size × text_height_factor`, gdzie `size` ma już skalę k;
  - `rotation` to kąt znormalizowany do [0, 360) (`round(a % 360, 9)`);
  - kolor, warstwa i przezroczystość jak wyżej.
- Pusty tekst albo wysokość ≤ 0 są pomijane.

### 9.9 Zapis

`zoom.extents(msp)` ustawia widok startowy na cały rysunek (błąd jest
ignorowany). Potem `mkdir(parents=True)` i `doc.saveas(path)`.
`add_page()` zwraca `Counter` typów encji do raportu.

---

## 10. Potok konwersji (`converter.py`)

### Opcje: `ConvertOptions`

| Pole | Domyślnie | Pole | Domyślnie |
|---|---|---|---|
| `pages` | `None` (wszystkie) | `fills` | `"hatch"` |
| `single_file` | `False` | `text` | `True` |
| `units` | `"mm"` | `merge_text` | `False` |
| `scale` | `1.0` | `text_height_factor` | `0.7` |
| `curves` | `"spline"` | `dxf_version` | `"R2010"` |
| `flatten_tol` (mm) | `0.01` | `preview` | `False` |
| `detect_arcs` | `True` | `dwg` | `False` |
| `join` | `False` | `dwg_version` | `"R2018"` |
| `layers` | `"by-color"` | `oda_path` | `None` |

### `convert(input_path, output=None, options=None) -> ConversionReport`

```
plik nie istnieje                  → ConversionError("nie znaleziono pliku: …")
katalog, rdzeń = resolve_output(src, output)
open_pdf (PdfError → ConversionError)
numery, ostrzeżenia = select_pages(opts.pages, page_count)
jeden_plik = single_file lub jedna strona
x_offset = 0
dla każdej strony:
    page = extract_page(n − 1, with_text=opts.text)
    _check_content(page) → skan albo pusta: oznacz i pomiń
    tr = page_transform(page, units, scale, offset=(x_offset, 0))
    dxf_page = transform_page(page, tr)
    jeśli merge_text: dxf_page.texts = merge_texts(dxf_page.texts)
    dxf_page, stats = postprocess_page(dxf_page, detect_arcs, join)
    jeden_plik: wspólny writer.add_page(); x_offset += szerokość × 1.1
    inaczej:    nowy writer, zapis "rdzeń_pN.dxf"
jeden_plik i coś zapisano → zapis "rdzeń.dxf"
preview → _make_previews; dwg → _make_dwg
```

**Nazwy i miejsce plików (`resolve_output`):**

- brak `-o`: obok PDF, rdzeń = nazwa PDF;
- `-o` zakończone `/` lub `\` albo istniejący katalog: ten katalog,
  rdzeń = nazwa PDF;
- inaczej: katalog nadrzędny, a rdzeń to `stem`, gdy rozszerzenie to
  `.dxf`, w przeciwnym razie cała nazwa.

Plik nazywa się `rdzeń.dxf` albo `rdzeń_pN.dxf` przy wielu plikach.

**`select_pages`:**

- 0 stron → `ConversionError("PDF nie zawiera żadnych stron")`;
- brak wyboru → wszystkie strony;
- numery większe niż liczba stron są pomijane z ostrzeżeniem;
- gdy nie zostaje żadna strona → `UsageError`, kod 2.

**Klasyfikacja strony (`_check_content`):**

- **skan**: `image_count > 0`, pokrycie obrazami ≥ 0.3 i
  (liczba podścieżek + fragmentów tekstu) ≤ 5. Ostrzeżenie: „strona
  wygląda na skan (obraz bez danych wektorowych) — pominięta”;
- **pusta**: brak kształtów i tekstu. Ostrzeżenie: „strona nie zawiera
  danych wektorowych — pominięta”;
- **wektorowa z obrazami**: ostrzeżenie „strona zawiera obrazy (N) —
  obrazy nie są przenoszone do DXF”.

`--single-file` układa strony wzdłuż osi X z odstępem
`PAGE_GAP = 0.1` × szerokość strony.

### Raport

- `PageReport(number, output, entities: Counter, duplicates_removed, joined, warnings, raster, empty)`.
  Właściwość `skipped` = `raster or empty`.
- `ConversionReport(input, pages, outputs, previews, dwg_outputs, dwg_errors, warnings)`:
  - `no_vector_data`: są strony i wszystkie są pominięte;
  - `looks_scanned`: co najmniej jedna strona to skan.

**`_make_previews`:** dla każdego DXF wywołuje `render_preview`. Brak
matplotlib (`PreviewUnavailable`) daje jedno ostrzeżenie i przerywa
tworzenie podglądów. Inne błędy dają ostrzeżenie dla danego pliku.
Podgląd nigdy nie psuje konwersji.

**`_make_dwg`:** dla każdego DXF wywołuje `dxf_to_dwg`. `ConverterNotFound`
dodaje błąd i przerywa (nie ma sensu próbować dalej). Inny `DwgError`
dodaje błąd i konwersja idzie dalej. DXF zawsze zostaje.

Wyjątki: `ConversionError` (kod 1) i `UsageError` (kod 2).

---

## 11. Wiersz poleceń (`cli.py`)

```
pdf2dxf INPUT.pdf [-o OUT.dxf | -o KATALOG/]
        [--pages 1,3-5] [--single-file]
        [--units mm|cm|m|in|pt] [--scale N]
        [--curves spline|polyline] [--flatten-tol MM]
        [--detect-arcs | --no-detect-arcs] [--join]
        [--layers by-color|by-ocg|single] [--fills hatch|outline|ignore]
        [--no-text] [--merge-text] [--text-height-factor F]
        [--dxf-version R2000|R2004|R2007|R2010|R2013|R2018] [--preview]
        [--dwg] [--dwg-version R2000…R2018] [--oda-path PATH]
        [-v] [--version] [-h]
```

Pomoc jest po polsku i podzielona na grupy: strony, jednostki i skala,
geometria, styl, tekst, wynik, DWG. Epilog wymienia kody wyjścia.
`--detect-arcs` to `argparse.BooleanOptionalAction`.

- `parse_pages("1,3-5")` daje posortowaną listę bez powtórzeń. Błąd
  (`0`, `3-1`, `a`, pusty napis) to `ArgumentTypeError`, czyli kod 2.
- `_positive_float` przyjmuje przecinek dziesiętny. Wartość ≤ 0 to błąd.

**Przebieg `main(argv)`:**

1. Parsowanie argumentów. Błąd argparse daje kod 2.
2. Logowanie: `DEBUG` przy `-v`, inaczej `WARNING`.
3. `_utf8_console()`: `reconfigure(errors="replace")` dla stdout i stderr,
   żeby polskie znaki nie przerywały wypisywania w konsoli Windows.
4. `convert(...)`:
   - `UsageError` → wypisanie sposobu użycia i `pdf2dxf: błąd: …`, kod 2;
   - `ConversionError` → `pdf2dxf: błąd: …`, kod 1.
5. Raport na stdout, błędy DWG na stderr (`pdf2dxf: błąd DWG: …`).
6. `no_vector_data` → kod 3. Komunikat o skanie („wygląda na skan.
   Potrzebna jest wektoryzacja (np. potrace…)”) pojawia się tylko wtedy,
   gdy była strona rastrowa.
7. Błędy DWG → kod 1, inaczej kod 0.

**Format raportu (`format_report`):**

```
pdf2dxf: STOJAK BUTY.pdf
  ostrzeżenie: …                        (ostrzeżenia całego dokumentu)
  strona 1 → out\STOJAK BUTY.dxf
    encje: CIRCLE 32, LINE 252, LWPOLYLINE 98, SPLINE 348 (razem 730)
    usunięte duplikaty: 0
    połączone odcinki: N                (tylko gdy > 0)
    ostrzeżenie: …
  podgląd: out\STOJAK BUTY.png
  DWG: out\STOJAK BUTY.dwg
```

Encje są posortowane alfabetycznie. Strona bez encji, która nie została
pominięta, dostaje „encje: brak”.

| Kod | Znaczenie |
|---|---|
| 0 | OK |
| 1 | błąd: brak pliku, uszkodzony lub zaszyfrowany PDF, błąd zapisu, nieudana konwersja DWG |
| 2 | złe argumenty, także `--pages` bez żadnej istniejącej strony |
| 3 | brak danych wektorowych (skan albo pusty PDF) |

---

## 12. Podgląd PNG z DXF (`preview.py`)

PNG jest renderowany z **gotowego DXF**, nie z PDF, więc pokazuje to, co
zobaczy program CAD.

`render_png(doc|ścieżka, png_path, *, extents=None, size_inches=None, dpi=100, max_pixels=2000)`:

1. Import matplotlib. Brak daje `PreviewUnavailable("podgląd wymaga matplotlib: pip install \"pdf2dxf[preview]\"")`.
2. Zakres: `ezdxf.bbox.extents(msp, fast=True)` z marginesem 2 % dłuższego
   boku. Pusty rysunek daje `(0, 0, 1, 1)`.
3. Rozmiar: dłuższy bok ma `max_pixels` pikseli przy `dpi`. Każdy bok ma
   co najmniej 0.5 cala.
4. `Figure(figsize, dpi)` + `FigureCanvasAgg`. Osie zajmują całą figurę:
   `add_axes((0, 0, 1, 1))`.
5. `Configuration(background_policy=WHITE, color_policy=COLOR, lineweight_policy=ABSOLUTE, lineweight_scaling=72/25.4)`.
6. `Frontend(RenderContext(doc), MatplotlibBackend(ax, adjust_figure=False), config).draw_layout(msp, finalize=True)`.
7. `set_xlim/ylim` na zakres, `set_axis_off()`,
   `savefig(dpi, facecolor="white")`.

`render_preview(dxf)` zapisuje `<nazwa>.png` obok DXF.

**Ważne:** backend matplotlib w ezdxf 1.4 przekazuje lineweight w mm jako
szerokość linii w punktach, przez co linie wychodzą około 2.8× za cienkie.
Rozwiązaniem jest `lineweight_scaling = 72/25.4`. Wykrył to test wizualny:
IoU wzrosło z 0.90 do 0.97.

---

## 13. Konwersja do DWG (`dwg.py`)

Stałe:

- `DWG_VERSIONS = ("R2000", "R2004", "R2007", "R2010", "R2013", "R2018")`;
- `ODA_URL = "https://www.opendesign.com/guestfiles/oda_file_converter"`;
- `ENV_VAR = "PDF2DXF_ODA_PATH"`;
- `EXE_NAMES = ("ODAFileConverter.exe", "ODAFileConverter")`.

Wyjątki:

- `DwgError`: konwersja się nie udała, DXF zostaje;
- `ConverterNotFound(DwgError)`: komunikat „nie znaleziono ODA File
  Converter — plik DXF został zapisany, ale DWG nie. Pobierz i zainstaluj
  program ze strony {ODA_URL}, a jeśli jest w nietypowym miejscu, wskaż
  plik ODAFileConverter opcją --oda-path albo zmienną środowiskową
  PDF2DXF_ODA_PATH.”

### `find_converter(explicit=None, *, search_roots=None)`

Kolejność wyszukiwania:

1. `explicit` (`--oda-path`), potem zmienna `PDF2DXF_ODA_PATH`. Może
   wskazywać plik albo katalog z plikiem. **Jawnie wskazana ścieżka,
   która nie istnieje, kończy wyszukiwanie wynikiem `None`**, żeby
   program nie użył po cichu innej instalacji.
2. `shutil.which()` dla obu nazw pliku, czyli `PATH`.
3. `<root>/ODA/ODAFileConverter*/ODAFileConverter.exe` dla każdego
   katalogu z `%ProgramFiles%`, `%ProgramW6432%`, `%ProgramFiles(x86)%`
   i `C:\Program Files`. Wybierana jest **najnowsza wersja**: klucz to
   krotka liczb z nazwy katalogu, np. `ODAFileConverter 27.10.0` →
   `(27, 10, 0)`.
4. macOS i Linux: `/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter`,
   `/usr/bin/ODAFileConverter`, `/usr/local/bin/ODAFileConverter`.
5. Ścieżka skonfigurowana w ezdxf (`odafc.get_win_exec_path()` albo
   `get_unix_exec_path()`), jeśli plik istnieje.

Własne wyszukiwanie jest potrzebne, bo domyślna ścieżka w ezdxf nie pasuje
do nowszych instalatorów ODA. Tworzą one katalog z numerem wersji.

### `dxf_to_dwg(dxf, dwg=None, *, version="R2018", converter=None) -> Path`

1. Cel to domyślnie `dxf.with_suffix(".dwg")`. Nieznana wersja daje
   `DwgError`.
2. `find_converter`. `None` daje `ConverterNotFound`.
3. `ezdxf.options.set("odafc-addon", "win_exec_path" | "unix_exec_path", exe)`.
   Zmiana działa tylko w pamięci procesu, bez zapisu konfiguracji na dysk.
4. Istniejący DWG jest usuwany.
5. `odafc.convert(src, dest, version=version, audit=True, replace=True)`:
   - `ODAFCNotInstalledError` → `ConverterNotFound`;
   - `ODAFCError` lub `OSError` → `DwgError`.
6. **Sprawdzenie wyniku:** brak pliku albo rozmiar 0 daje
   `DwgError("ODA File Converter nie utworzył pliku …")`. Powód: w ezdxf
   1.4.5 `odafc.convert` tworzy wyjątek `UnknownODAFCError`, ale go nie
   rzuca.

Sprawdzone z prawdziwym ODA 27.10.0: DWG R2018 zaczyna się od `AC1032`,
a po odczycie z powrotem zgadzają się encje, jednostki i zakres.

**Polskie znaki:** DXF i DWG od R2007 zapisują Unicode bez zmian.
W R2000 i R2004 litery spoza strony kodowej ANSI_1252 są zapisywane jako
`\U+017C`. Robią tak i ezdxf, i ODA, który ignoruje `$DWGCODEPAGE`.

---

## 14. Aplikacja okienkowa (`gui.py`)

### 14.1 Działanie z punktu widzenia użytkownika

1. Użytkownik upuszcza pliki PDF na listę, klika „Dodaj PDF…” albo klika
   w pustą listę. Pliki trafiają na listę **bez konwersji**. PDF upuszczony
   na ikonę `.exe` (argument wiersza poleceń) też tylko trafia na listę.
2. Po prawej stronie widać podgląd zaznaczonej strony PDF.
3. „Konwertuj” zapisuje DWG obok każdego PDF, z tą samą nazwą.

### 14.2 Układ okna

Tytuł `PDF → DWG  (pdf2dxf 0.1.0)`, rozmiar startowy 1040×720,
minimalny 900×620. Siatka ma 2 kolumny o równej szerokości
(`uniform="half"`). Wiersz 0 ma wagę 3, wiersz 3 (log) wagę 1.

```
┌─ Pliki PDF do konwersji ─────────────┬─ Podgląd ────────────────────────────┐ wiersz 0
│ ┌──────────────────────────────────┐ │ ┌──────────────────────────────────┐ │
│ │ ✓  STOJAK BUTY.pdf               │ │ │                                  │ │
│ │ •  stojak.pdf                    │ │ │        obraz strony PDF          │ │
│ │                                  │ │ │     (Canvas, tło #9ca3af)        │ │
│ │ (pusta lista: „Upuść tutaj pliki │ │ │                                  │ │
│ │  PDF albo kliknij, aby wybrać”)  │ │ │                                  │ │
│ └──────────────────────────────────┘ │ │                                  │ │
│ [Dodaj PDF…] [Usuń zazn.] [Wyczyść]  │ │                                  │ │
├─ Ustawienia ─────────────────────────┤ │                                  │ │ wiersz 1
│ Jednostki: [mm ▾]   Skala 1 : [1   ] │ └──────────────────────────────────┘ │
│ Wersja DWG: [R2018 ▾]                │                                      │
│ Krzywe: (•) SPLINE (gładkie krzywe)  │ [◀]  stojak.pdf — strona 1 z 2  [▶]  │
│         ( ) polilinie (np. dla CNC)  │                                      │
│ [ ] Zachowaj też plik DXF            │                                      │
├──────────────────────────────────────┴──────────────────────────────────────┤
│ ODA File Converter: ODAFileConverter 27.10.0 ✓    [Pobierz ODA File Conv.]* │ wiersz 2
├─────────────────────────────────────────────────────────────────────────────┤
│ log (ScrolledText, Consolas 9, wysokość 6 wierszy, tylko do odczytu)        │ wiersz 3
├─────────────────────────────────────────────────────────────────────────────┤
│ status                            [Otwórz folder z wynikiem] [ Konwertuj ]  │ wiersz 4
└─────────────────────────────────────────────────────────────────────────────┘
  * przycisk widoczny tylko wtedy, gdy ODA nie został znaleziony
```

Podgląd zajmuje prawą kolumnę w wierszach 0–1 (`rowspan=2`), obok listy
plików i ustawień.

Szczegóły widżetów:

- **Lista:** `tk.Listbox` z `selectmode="extended"`, font Segoe UI 10, tło
  `#f4f6f8`, przy przeciąganiu nad oknem `#dbeafe`. Pozycja ma postać
  `" {znacznik}  {nazwa}"`. Znaczniki i kolory:

  | Status | Znacznik | Kolor |
  |---|---|---|
  | `pending` | `•` | `#222222` |
  | `working` | `…` | `#1d4ed8` |
  | `ok` | `✓` | `#1a7f37` |
  | `error` | `✗` | `#b42318` |

  Pusta lista pokazuje na środku etykietę-podpowiedź (`place`), która po
  kliknięciu otwiera wybór pliku.
- **Ustawienia:**
  - „Jednostki” to combobox tylko do odczytu z `mm`, `cm`, `m`, `in` (bez
    `pt`);
  - „Skala 1 :” to pole tekstowe z wartością `1`;
  - „Wersja DWG” to combobox z `DWG_VERSIONS`;
  - „Krzywe” to dwie opcje: „SPLINE (gładkie krzywe)” i „polilinie (np. dla
    CNC)”;
  - pole wyboru „Zachowaj też plik DXF”.
- **Konwertuj:** styl `Convert.TButton`, Segoe UI 11 bold, padding (18, 6).
- **Status ODA:** zielony napis
  `ODA File Converter: {nazwa katalogu} ✓` albo czerwony
  „Brak ODA File Converter — powstanie tylko DXF.” z przyciskiem, który
  otwiera `ODA_URL` w przeglądarce.

### 14.3 Logika niezależna od okna (testowalna)

- `GuiSettings(units="mm", scale=1.0, curves="spline", keep_dxf=False, dwg_version="R2018")`.
  `.options()` daje
  `ConvertOptions(units, scale, curves, dwg=True, dwg_version)`.
  Pozostałe opcje mają wartości domyślne: łuki włączone, HATCH, tekst,
  warstwy wg koloru, DXF R2010.
- `parse_scale(text)`:
  - przecinek zamienia na kropkę, usuwa spacje;
  - `a:b` i `a/b` dają `b/a`, a samo `n` daje `n`;
  - przykłady: `50` → 50, `1:50` → 50, `1/100` → 100, `2:1` → 0.5;
  - wartość ≤ 0 daje `ValueError`, a `1:0` daje `ZeroDivisionError`.
- `pdf_paths(items)` daje `(istniejące pliki .pdf, odrzucone)`. Wielkość
  liter w rozszerzeniu nie ma znaczenia.
- `run_job(pdf, settings) -> JobResult(pdf, text, ok, outputs)` **nigdy nie
  rzuca wyjątku**:
  - `ConversionError` lub `UsageError` → `"{nazwa}: błąd: …"`;
  - inny wyjątek → `"nieoczekiwany błąd:"` z tracebackiem;
  - tekst to `format_report(report)` i ewentualnie dopiski: „zapisano
    tylko DXF”, „błąd DWG: …”, „brak danych wektorowych — PDF wygląda na
    skan albo jest pusty”;
  - gdy DWG powstał i `keep_dxf=False`, DXF z odpowiadającym mu DWG jest
    **usuwany**. W przeciwnym razie DXF trafia do `outputs`;
  - `ok = bool(dwg_outputs) and not dwg_errors`.

### 14.4 Stan okna i reguły listy

Stan klasy `App`:

- `files: list[FileEntry(path, status)]`;
- `jobs: Queue[(Path, GuiSettings)]` i `results: Queue[JobResult | str]`;
- `busy`, `last_folder`;
- `preview_path`, `preview_page`, `preview_pages`;
- `_photo`: referencja do obrazu (bez niej Tk usuwa obraz);
- `_resize_job`.

**`add_files(items)`:**

1. `pdf_paths`. Każda odrzucona pozycja trafia do logu: „Pominięto (to nie
   jest plik PDF): …”.
2. Gdy okno nie konwertuje, z listy znikają pliki gotowe (`ok`).
3. Duplikaty są pomijane (porównanie `Path.resolve()`).
4. Zaznaczany jest pierwszy nowy plik (albo pierwszy podany) i pokazywany
   jego podgląd.
5. Status: „Kliknij „Konwertuj”, aby zapisać DWG.”

**`convert_files()`:**

1. Nic nie robi, gdy trwa konwersja. Przy pustej liście pisze do logu
   „Najpierw dodaj pliki PDF.”
2. Ustawienia są odczytywane **w chwili kliknięcia**. Zła skala daje
   w logu „Błąd: niepoprawna skala „…” — wpisz np. 50 albo 1:50”.
3. Do konwersji idą pliki o statusie innym niż `ok`. **Gdy wszystkie są
   `ok`, konwertowane są wszystkie ponownie**, np. po zmianie skali.
4. Wybrane pliki dostają status `working` i trafiają do kolejki `jobs`
   razem z ustawieniami. Potem `busy = True` i start wątku-demona
   `_worker`.

**Przyciski:**

- „Konwertuj” jest aktywny, gdy lista nie jest pusta i nic się nie
  konwertuje;
- „Usuń zaznaczone” i „Wyczyść” są aktywne, gdy lista nie jest pusta
  i nic się nie konwertuje;
- „Otwórz folder z wynikiem” jest aktywny po pierwszym wyniku
  i wywołuje `os.startfile(last_folder)`.

`_refresh_list()` przebudowuje listę, zachowuje zaznaczenie (według
ścieżki) i pokazuje lub ukrywa podpowiedź.

### 14.5 Wątki

Tk jest dotykany **tylko z wątku głównego**.

```
wątek roboczy (_worker):                 wątek główny (_poll co 100 ms):
  dopóki jobs niepusta:                    dopóki results niepusta:
    results.put("Konwertuję: X …")           "done"     → busy=False, status „Gotowe: N plik(ów)
    results.put(run_job(pdf, ustawienia))                 skonwertowano[, błędy: M]”
  results.put("done")                        str        → status + log
                                             JobResult  → log, status pliku ok/error,
                                                          last_folder, przycisk „Otwórz folder”
                                           root.after(100, _poll)
```

### 14.6 Podgląd

`show_preview(path="", page=None)` działa tak:

- `path=""` odświeża bieżący plik, `None` czyści podgląd, a ścieżka
  ustawia nowy plik od strony 0;
- rozmiar canvasu jest odczytywany (co najmniej 50 px), a strona
  renderowana przez `open_pdf(path).render_png(page, w−16, h−16)`;
- obraz powstaje jako `tk.PhotoImage(data=base64(png))`, wyśrodkowany na
  canvasie. Tk 9 czyta PNG natywnie, bez Pillow;
- etykieta: `"{nazwa}   —   strona {n} z {N}"`;
- błąd daje biały napis „Nie można wyświetlić podglądu:\n{błąd}”, a okno
  działa dalej;
- bez pliku pojawia się napis „Podgląd pojawi się\npo dodaniu pliku PDF”;
- ◀ ▶ są aktywne przy > 1 stronie. `turn_page(±1)` przewija w kółko
  (modulo);
- zdarzenie `<Configure>` canvasu ponownie renderuje podgląd 150 ms po
  ostatniej zmianie rozmiaru (`after_cancel` + `after`), żeby nie migał.

### 14.7 Przeciąganie plików (tkinterdnd2)

- `_make_root()` zwraca `TkinterDnD.Tk()`, a przy braku pakietu lub
  biblioteki tkdnd zwykłe `tk.Tk()`. Bez DnD podpowiedź brzmi „Kliknij,
  aby wybrać pliki PDF”.
- Celami upuszczania są ramka plików, lista, podpowiedź i canvas
  podglądu: `drop_target_register(DND_FILES)`.
- `<<Drop>>` wywołuje `root.tk.splitlist(event.data)`. tkdnd podaje
  ścieżki ze spacjami w nawiasach klamrowych, np.
  `{C:/a b.pdf} C:/c.pdf`. Potem `add_files`.
- `<<DropEnter>>` i `<<DropLeave>>` zmieniają kolor tła listy.
- Każda obsługa zdarzenia zwraca `event.action`.

### 14.8 Pozostałe

- `root.report_callback_exception` wypisuje traceback do logu, bo
  aplikacja nie ma konsoli.
- `_dpi_aware()`: `ctypes.windll.shcore.SetProcessDpiAwareness(1)` daje
  ostre czcionki przy skalowaniu ekranu.
- `main(argv)`:
  1. pliki z `sys.argv[1:]`;
  2. DPI;
  3. okno;
  4. `root.after(300, add_files(pliki))`;
  5. `mainloop()`.

---

## 15. Budowanie `PDF2DWG.exe`

### Punkt wejścia: `scripts/pdf2dwg_gui.py`

```python
try:
    from pdf2dxf.gui import main
    code = main()
except Exception:
    _fatal(traceback.format_exc())   # %TEMP%\PDF2DWG-blad.txt + MessageBoxW (ikona błędu 0x10)
    code = 1
raise SystemExit(code)
```

Aplikacja okienkowa nie ma konsoli. Bez tego zabezpieczenia błąd przy
starcie kończyłby program bez żadnego komunikatu.

### Skrypt: `scripts/build_exe.py`

Wywołuje `PyInstaller.__main__.run(args)` z argumentami:

```
scripts/pdf2dwg_gui.py
--name PDF2DWG            (z --console: PDF2DWG-console)
--onefile
--windowed                (z --console: --console)
--noconfirm --clean
--paths src
--collect-all tkinterdnd2      # biblioteka tkdnd (DLL + skrypty Tcl)
--distpath dist  --workpath build/pyinstaller  --specpath build
--exclude-module matplotlib PIL pytest _pytest pymupdf_fonts IPython scipy pandas
                 tkinter.test pydoc_data
--icon build/PDF2DWG.ico
```

- **Nie wolno wykluczać `unittest`.** Importuje go `pyparsing`, zależność
  ezdxf. Bez niego `.exe` kończył się od razu, bez komunikatu.
- Ikona powstaje w Pillow: niebieski zaokrąglony kwadrat
  `(29, 78, 216)`, napisy „PDF”, „↓” i „DWG” fontem `arialbd.ttf`,
  rozmiary 16–256 px. Bez Pillow używana jest ikona domyślna.
- PyMuPDF i ezdxf dołącza PyInstaller wraz z `pyinstaller-hooks-contrib`.
- Wynik: `dist\PDF2DWG.exe`, około 52 MB, jeden plik. Zawiera Pythona
  i wszystkie biblioteki. Na innym komputerze potrzebny jest tylko ODA
  File Converter.
- Pierwsze uruchomienie trwa kilka sekund (rozpakowanie do `%TEMP%`).
  SmartScreen może ostrzec przed niepodpisanym programem.

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[build]"
.\.venv\Scripts\python.exe scripts\build_exe.py
```

---

## 16. Testy

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest -m "not slow"
```

Ostatnie polecenie pomija test wizualny i test z prawdziwym ODA. Obecny
wynik: **207 passed**. To 139 funkcji testowych, wiele
sparametryzowanych.

### Zasady

- Testowe PDF-y są **generowane w fixture'ach** przez PyMuPDF, żeby
  geometria była znana co do liczby. Binarnych PDF-ów nie ma w repozytorium
  (poza `samples/`).
- `conftest.make_pdf(*draws, name, width=595, height=842, rotation=0)`:
  każda funkcja `draw(page)` rysuje jedną stronę. Obrót jest ustawiany
  **po** narysowaniu, więc współrzędne dotyczą strony nieobróconej.
- `conftest.raw(stream)` podmienia strumień treści strony na surowe
  operatory PDF (oś Y w górę). Służy do przypadków, których API PyMuPDF
  nie umie wygenerować, np. linii o grubości 0.
- `helpers.read_dxf(path)` otwiera DXF ponownie i sprawdza, że
  `doc.audit()` nie ma ani błędów, ani poprawek (test 14 z SPEC).
- `helpers.convert_one(pdf, **opcje)` daje `(raport, dokument)`.
- Polskie znaki w testach: font `"notos"` z `pymupdf-fonts`. Wbudowana
  Helvetica nie ma polskich liter.

### Pliki testów

| Plik | Liczba funkcji | Co sprawdza |
|---|---|---|
| `test_extract.py` | 12 | linia, prostokąt (4 segmenty, zamknięty), orientacja `re`, obwód `qu`, podział na podścieżki, zamknięcie geometryczne z dociągnięciem, flaga `closePath`, styl, `parse_dashes`, `to_rgb`, `render_png` dla strony obróconej |
| `test_transform.py` | 9 | macierz obrotu = `page.rotation_matrix`, `Affine.then`, mm i odbicie Y, jednostki, skala, przesunięcie, obrót 90°, kąty, `transform_page` |
| `test_writer.py` | 4 | LINE/LWPOLYLINE, `$INSUNITS`, odrzucenie przestrzeni PDF, wersja DXF |
| `test_writer_helpers.py` | 9 | `nearest_aci`, czarny = ACI 7 bez true color, lineweight, nazwy warstw, pole ze znakiem, kontury HATCH (even-odd, nonzero w tym samym i przeciwnym kierunku, osobne wyspy) |
| `test_style.py` | 17 | okrąg jako SPLINE i polilinia, końce SPLINE, ścieżka mieszana, łączenie odcinków przez start, kolory, warstwy single i by-ocg, grubość, przezroczystość, audyt wszystkich wersji DXF, typ linii, HATCH, `fs`, `--fills outline/ignore`, białe tło, dziury |
| `test_text.py` | 13 | „Zażółć gęślą jaźń” bez zmian, wysokość i skala, kolor i warstwa, `--no-text`, tekst pod kątem 90° i 30°, tekst na stronie obróconej, tekst niewidoczny, `--merge-text` (łączenie, odległe słowa, szerokość, reguły) |
| `test_postprocess.py` | 21 | wykrywanie okręgu i jego warianty, elipsa to nie okrąg, ćwiartka, półokrąg zgodnie z ruchem wskazówek, zaokrąglony prostokąt jako polilinia z bulge, HATCH koła z bulge, `cubic_to_arc` w obie strony i odrzucenia, łączenie łuków przez start, duplikaty (linie, prostokąty, krawędź, dowolny start, wypełnienia), mikroodcinek zamykający, ćwiartki o sumie > 360°, zaokrąglanie, `--join` (rozgałęzienia, łuki) |
| `test_pages.py` | 10 | strona obrócona wygląda jak w przeglądarce, wymiary, sam obraz daje kod 3, skan w dokumencie mieszanym, logo to nie skan, pusty PDF daje kod 3 bez komunikatu o skanie, plik na stronę, `--pages`, brakujące strony, `--single-file` |
| `test_preview.py` | 3 | **test wizualny** (spline i polyline), `--preview`, podgląd na stronę |
| `test_cli_e2e.py` | 15 | `--help`, `python -m pdf2dxf`, kod 2, `parse_pages`, przypadki 1, 2 i 7 z SPEC, raport, miejsce wyniku, katalog `-o`, kod 1 (brak pliku, nie PDF), wartości domyślne |
| `test_dwg.py` | 13 | `find_converter` (plik, katalog, zmienna, katalog z wersją, brak), `dxf_to_dwg` z atrapą, brak ODA, brak pliku wynikowego, błąd ODAFC, CLI `--dwg`, DXF zostaje bez ODA, DWG na stronę, wersje, **prawdziwy ODA** (`slow`) |
| `test_gui.py` | 13 | `parse_scale`, `pdf_paths`, `run_job` (tylko DWG, zachowaj DXF i skala, bez ODA, zły plik, skan), okno czeka na „Konwertuj”, reguły listy, podgląd i strony, uszkodzony PDF, upuszczenie ścieżek ze spacjami |

### Przypadki z SPEC (sekcja 12)

| Nr | Oczekiwanie | Test |
|---|---|---|
| 1 | linia (100,100)–(200,100) pt → `LINE` 35.2778 mm, Y odbite | `test_case1_line_length_and_y_flip` |
| 2 | prostokąt → zamknięta `LWPOLYLINE`, 4 wierzchołki | `test_case2_rect_closed_lwpolyline` |
| 3 | okrąg r = 50 pt → `CIRCLE` r = 17.639 mm / `SPLINE` / `LWPOLYLINE` | `test_case3_*` |
| 4 | krzywa Béziera → `SPLINE` z poprawnymi końcami | `test_case4_bezier_spline_endpoints` |
| 5 | polski tekst bez zmian | `test_case5_polish_text_roundtrip` |
| 6 | czerwony → `(255,0,0)`, warstwa `PDF_FF0000`; czarny → ACI 7 | `test_case6_red_and_black` |
| 7 | `--scale 100`, `--units in` + `$INSUNITS` | `test_case7_scale`, `test_case7_units_inches` |
| 8 | linia przerywana → własny typ linii | `test_case8_dashed_line_linetype` |
| 9 | wypełniony prostokąt → `HATCH` SOLID | `test_case9_filled_rect_hatch` |
| 10 | strona obrócona o 90° | `test_case10_rotated_page_matches_viewer` |
| 11 | sam obraz → ostrzeżenie i kod 3 | `test_case11_image_only_exit_3` |
| 12 | dwie identyczne linie → jedna | `test_case12_duplicate_lines` |
| 13 | wiele stron, `--pages`, `--single-file` | `test_case13_*` |
| 14 | każdy DXF otwiera się i przechodzi audyt | `helpers.read_dxf` (w każdym teście), `test_case14_all_versions_audit_clean` |
| 15 | test wizualny IoU > 0.9 | `test_case15_visual_overlay` (`slow`) |

**Test wizualny:** rysunek testowy zawiera linię, prostokąt, okrąg, krzywą
Béziera, linię przerywaną, wypełnienie, prostokąt z zaokrąglonymi rogami
i owal.

1. Strona PDF jest rasteryzowana przez PyMuPDF w skali szarości przy
   100 dpi.
2. DXF jest renderowany przez `render_png` w tym samym obszarze strony
   i rozmiarze.
3. Maski ciemnych pikseli (< 160) są poszerzane o 2 px.
4. Wymaganie: IoU > 0.9. Uzyskane: 0.97 dla obu trybów krzywych.

Tekst jest pominięty, bo font zastępczy ma inne kształty liter.

**Test okna:** okno jest tworzone i ukrywane (`withdraw`). Bez środowiska
graficznego test jest pomijany. Konwersja korzysta z atrapy ODA:
`odafc.convert` zapisuje plik zaczynający się od `AC1032`.

---

## 17. Odtworzenie programu krok po kroku

1. **Środowisko:** zainstalować Pythona ≥ 3.10 (sprawdzony 3.15.2,
   64-bit) i opcjonalnie ODA File Converter.
   ```powershell
   python -m venv .venv
   ```
   ```powershell
   .\.venv\Scripts\python.exe -m pip install -e ".[dev,build]"
   ```
2. **Rozpoznanie przed pisaniem kodu:** uruchomić krótki skrypt, który
   generuje PDF z każdym rodzajem elementu i wypisuje
   `page.get_drawings()` oraz `page.get_text("dict")`. Porównać wynik
   z [sekcją 6.2](#62-co-naprawdę-zwraca-pymupdf-1282). Nowsza wersja
   PyMuPDF może się różnić.
3. **Faza 0, szkielet:** `pyproject.toml`, `src/pdf2dxf/`, CLI z pełną
   listą opcji, `python -m pdf2dxf --help`.
4. **Faza 1, linie:**
   - `model.py`;
   - backend (tylko ścieżki, `items_to_subpaths`, `re`/`qu`);
   - `transform.py` z obrotem, odbiciem, jednostkami i skalą;
   - writer z `LINE` i `LWPOLYLINE`, `$INSUNITS`;
   - `converter.py`, CLI.

   Testy 1, 2, 7 i 14.
5. **Faza 2, krzywe i styl:** SPLINE przez `to_bsplines_and_vertices`,
   polilinie przez `flattening`, kolory i ACI, lineweight, warstwy, typy
   linii, HATCH z regułą nonzero, pomijanie tła. Testy 3 (bez łuków), 4,
   6, 8 i 9.
6. **Faza 3, tekst:** `extract_texts`, `TEXT` ze stylem `arial.ttf`, kąt,
   tekst niewidoczny, `--merge-text`. Test 5 i tekst obrócony.
7. **Faza 4, postprocessing i strony:** zaokrąglanie, odcinki zerowe,
   deduplikacja, `cubic_to_arc` i `merge_arcs`, CIRCLE/ARC/bulge,
   `--join`, wiele stron, `--single-file`, skany, raport, kody wyjścia.
   Testy 3 (pełny) i 10–13.
8. **Faza 5, podgląd:** `preview.py` z poprawką `lineweight_scaling`, test
   wizualny 15, README.
9. **Faza 6, DWG:** `dwg.py` z własnym wyszukiwaniem ODA i sprawdzaniem
   pliku wynikowego, opcje `--dwg`, `--dwg-version`, `--oda-path`.
10. **Faza 7, okno i `.exe`:** `gui.py` według [sekcji 14](#14-aplikacja-okienkowa-guipy),
    `PdfBackend.render_png`, `scripts/pdf2dwg_gui.py`,
    `scripts/build_exe.py`.
11. Po każdej fazie: `pytest` na zielono, potem commit.

**Kontrola na prawdziwych plikach:** wszystkie 5 plików z `samples/`
(eksporty macOS Quartz, panele do CNC, tekst zamieniony na krzywe)
konwertują się z kodem 0. Przykład, `STOJAK BUTY.pdf`:
`CIRCLE 32, LINE 252, LWPOLYLINE 98, SPLINE 348 (razem 730)`. Przed
poprawką mikroodcinków zamykających było tylko 10 okręgów zamiast 32.
Zaokrąglone narożniki w tych plikach nie są łukami okręgu, więc zostają
`SPLINE`. To zachowanie poprawne.

---

## 18. Pułapki bibliotek (ważne przy odtwarzaniu)

| Problem | Skutek | Rozwiązanie |
|---|---|---|
| PyMuPDF 2.x wymaga `onnxruntime` | brak instalacji na Pythonie 3.15 | `pymupdf>=1.24,<2` |
| `dashes` to napis PDF, a nie lista | błąd parsowania | regex w `parse_dashes` |
| `closePath` zawodny, okrąg ma `closePath=False` | otwarte kontury | zamknięcie także geometryczne (tol 1e-3 pt) |
| orientacja `re` = 1 to obieg przeciwny do wskazówek **na ekranie** | złe dziury przy nonzero | kolejność rogów z sekcji 6.5 |
| `qu` ma wierzchołki `ul, ur, ll, lr` | „klepsydra” zamiast czworokąta | obwód `ul → ur → lr → ll` |
| współrzędne strony obróconej są nieobrócone | rysunek obrócony w DXF | własna macierz obrotu |
| `draw_line(width=0)` zapisuje domyślną grubość | test grubości 0 nie działa | surowy strumień treści (`conftest.raw`) |
| `Shape.finish()` ma domyślnie `closePath=True` | testy otwartych ścieżek | jawne `closePath=False` |
| float32 w eksportach (macOS Quartz): mikroodcinek po `h` i suma łuków 360.00001° | okręgi nierozpoznane | `ZERO_LENGTH_TOL_PT` + `_reconnect`, `FULL_CIRCLE_SLACK` |
| punkty kontrolne SPLINE w ezdxf to tablice numpy | porównania w testach | indeksowanie i `pytest.approx` |
| backend matplotlib w ezdxf 1.4 bierze lineweight w mm jako pt | podgląd 2.8× za cienki | `lineweight_scaling = 72/25.4` |
| `odafc.convert` (ezdxf 1.4.5) nie rzuca `UnknownODAFCError` | „sukces” bez pliku DWG | sprawdzenie istnienia i rozmiaru pliku |
| domyślna ścieżka ODA w ezdxf bez numeru wersji | ODA „nie zainstalowany” | własne `find_converter` |
| ODA ignoruje `$DWGCODEPAGE` | `\U+` w R2000/R2004 | używać R2007+ (domyślnie R2018) |
| `Path("out/")` gubi końcowy ukośnik | `-o katalog/` traktowany jak plik | sprawdzanie napisu przed konwersją na `Path` |
| PyInstaller: wykluczony `unittest` | `.exe` zamyka się bez komunikatu | nie wykluczać; obsługa błędu startu w `pdf2dwg_gui.py` |
| tkdnd podaje ścieżki ze spacjami w `{…}` | rozbite ścieżki | `root.tk.splitlist(event.data)` |
| `tk.PhotoImage` bez trzymanej referencji | podgląd znika | `self._photo` |
| Tk z wątku roboczego | losowe awarie okna | kolejki + `after(100, _poll)` w wątku głównym |
| nazwa pliku z rozłożonym Unicode („Ó” jako O + znak łączący) | „nie znaleziono pliku” przy wpisywaniu nazwy | w skryptach wybierać pliki wzorcem (glob) |

---

## 19. Znane ograniczenia

- PDF to „spłaszczony” rysunek: nie ma w nim bloków, wymiarów
  asocjacyjnych ani informacji, które linie tworzą jeden obiekt.
- Skalę rysunku musi podać użytkownik, bo PDF jej nie przechowuje.
- Wzory kreskowania przychodzą jako wiele pojedynczych linii.
- Wszystkie fonty zastępuje `arial.ttf`. Położenie i wysokość tekstu są
  przybliżone, a szerokość napisu może się różnić od oryginału.
- Tekst zamieniony w PDF na krzywe przychodzi jako geometria.
- Rozpoznawane są tylko łuki **okręgów**. Elipsy i „gładkie” narożniki
  zostają jako `SPLINE`.
- Ścieżki przycinające są ignorowane, więc ukryta geometria pojawi się
  w DXF.
- Obrazy rastrowe nie są przenoszone. Skany nie są wektoryzowane.
- Tekst pionowy (`wmode=1`) i lustrzany trafia jako zwykły `TEXT` z kątem
  linii.
- Typy linii DXF nie mają fazy, więc początek wzoru kresek może się
  różnić od PDF.
- DWG powstaje tylko przez zewnętrzny ODA File Converter.
- Podgląd w oknie pokazuje stronę PDF, a nie wynik DWG. Render DXF
  wymagałby matplotlib, który powiększyłby `.exe` o kilkadziesiąt MB.

---

## 20. Licencje

- **PyMuPDF: AGPL-3.0.** Do użytku własnego nie ma to znaczenia.
  Rozpowszechnianie zamkniętego programu wymaga licencji komercyjnej
  Artifex albo wymiany backendu (np. na `pypdfium2`), czyli nowej
  implementacji `PdfBackend`. Dotyczy to także `PDF2DWG.exe`, który
  zawiera PyMuPDF: przed przekazaniem go poza firmę trzeba spełnić warunki
  AGPL, np. udostępnić kod źródłowy.
- **ezdxf:** MIT.
- **tkinterdnd2:** MIT. Pakiet zawiera bibliotekę tkdnd 2.10.3 z osobną
  licencją.
- **ODA File Converter:** darmowy program Open Design Alliance na
  licencji ODA. Nie jest dołączany do programu, użytkownik instaluje go
  sam.
