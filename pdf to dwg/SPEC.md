# pdf2dxf — konwerter PDF → DXF (opcjonalnie DWG)

## 1. Cel

Narzędzie wiersza poleceń w Pythonie, które zamienia **wektorowe** rysunki zapisane w PDF (eksporty z AutoCAD, Revit, ArchiCAD, Inkscape, programów do schematów itp.) na pliki **DXF** otwieralne w AutoCAD, BricsCAD, DraftSight, LibreCAD i QCAD. Opcjonalnie wynik może zostać skonwertowany do **DWG** zewnętrznym narzędziem.

Kryterium sukcesu całego projektu: typowy rysunek techniczny wyeksportowany z CAD do PDF po konwersji nakłada się wizualnie na oryginał, a wymiary zmierzone w programie CAD (po podaniu właściwej skali) zgadzają się z wymiarami na rysunku.

## 2. Dlaczego DXF, a nie DWG

- DXF to otwarty, udokumentowany format. Biblioteka `ezdxf` zapisuje go w pełni i bez zewnętrznych programów.
- DWG to format zamknięty, bez dojrzałej biblioteki do zapisu w czystym Pythonie.
- Każdy program CAD otwiera DXF, więc DXF jest pełnoprawnym wynikiem.
- DWG robimy na samym końcu (faza opcjonalna) jako konwersję gotowego DXF → DWG przez ODA File Converter, tylko jeśli użytkownik go zainstalował.

## 3. Zakres

### W zakresie (MVP)

- PDF wektorowe (rysunki „wydrukowane” z programów CAD/grafiki wektorowej).
- Linie, polilinie, prostokąty, krzywe Béziera, okręgi i łuki (wykrywane z krzywych), wypełnienia, tekst.
- Kolory, grubości linii, linie przerywane, warstwy (wg koloru lub z warstw PDF/OCG, jeśli są).
- Wiele stron, strony obrócone, skala rysunku i jednostki.

### Poza zakresem MVP

- Skany i PDF rastrowe — program ma je **wykryć i ostrzec**, a nie próbować wektoryzować.
- Odtwarzanie wymiarów jako obiektów DIMENSION — wymiary przyjdą jako linie + tekst.
- Odtwarzanie bloków, odnośników zewnętrznych, wzorów kreskowania (wzory przyjdą jako zwykłe linie).
- Tekst zamieniony w PDF na krzywe przyjdzie jako geometria (to normalne, nie błąd).

## 4. Stos technologiczny

- **Python 3.10+**
- **PyMuPDF** (`pip install pymupdf`, import `pymupdf` lub `fitz`) — ekstrakcja ścieżek (`page.get_drawings()`) i tekstu (`page.get_text("dict")`).
- **ezdxf** — zapis DXF (wersja R2010), moduł `ezdxf.path` do krzywych i kreskowań, `ezdxf.addons.drawing` (+ matplotlib) do podglądu PNG, `ezdxf.addons.odafc` do opcjonalnej konwersji DWG.
- **argparse** — CLI (bez dodatkowych zależności).
- **pytest** — testy.
- **matplotlib** — tylko jako opcjonalna zależność (`[preview]`) do podglądu PNG.

**Licencja:** PyMuPDF jest na licencji AGPL-3.0. Do użytku własnego nie ma to znaczenia, ale przy rozpowszechnianiu zamkniętego oprogramowania potrzebna byłaby licencja komercyjna Artifex albo podmiana backendu (np. `pypdfium2`). Dlatego **ekstrakcja ma być schowana za interfejsem** (`PdfBackend`), żeby dało się ją podmienić bez ruszania reszty kodu.

## 5. Architektura

Potok przetwarzania:

```
PDF → extract (backend PyMuPDF) → model pośredni → transform (układ współrzędnych, jednostki, skala)
    → postprocess (deduplikacja, łączenie, okręgi/łuki) → writer DXF → [opcjonalnie] DWG
```

Zasady:

- `extract` nie importuje `ezdxf`; `writer` nie importuje PyMuPDF. Łączy je wyłącznie model pośredni.
- Model pośredni jest w jednostkach PDF (punkty, oś Y w dół) — transformacja odbywa się w jednym miejscu.

### Struktura katalogów

```
pdf2dxf/
├── pyproject.toml
├── README.md
├── SPEC.md
├── samples/                 # przykładowe PDF-y użytkownika (opcjonalnie)
├── src/pdf2dxf/
│   ├── __init__.py
│   ├── __main__.py          # python -m pdf2dxf
│   ├── cli.py               # argparse, raport, kody wyjścia
│   ├── model.py             # dataclasses modelu pośredniego
│   ├── backends/
│   │   ├── base.py          # Protocol/ABC PdfBackend
│   │   └── pymupdf_backend.py
│   ├── transform.py         # PDF pt → jednostki DXF, odbicie osi Y, rotacja, skala
│   ├── postprocess.py       # deduplikacja, łączenie, wykrywanie okręgów/łuków
│   ├── writer.py            # zapis DXF przez ezdxf
│   ├── preview.py           # PNG z DXF (opcjonalne)
│   └── dwg.py               # DXF → DWG przez ODA (opcjonalne)
└── tests/
    ├── conftest.py          # fixture'y generujące testowe PDF-y
    ├── test_extract.py
    ├── test_transform.py
    ├── test_postprocess.py
    ├── test_writer.py
    └── test_cli_e2e.py
```

### Model pośredni (`model.py`)

- `Style`: kolor obrysu (RGB 0–1 lub `None`), kolor wypełnienia (RGB lub `None`), grubość linii w pt, wzór przerywania (lub `None`), nazwa warstwy z PDF (lub `None`), przezroczystość.
- Segmenty: `LineSeg(p1, p2)`, `CubicSeg(p1, c1, c2, p2)`.
- `SubPath`: lista segmentów + flaga `closed`.
- `Shape`: lista `SubPath`, `Style`, flagi `stroked` / `filled`, `even_odd`.
- `TextItem`: tekst, punkt bazowy (origin), rozmiar fontu w pt, kąt w stopniach, nazwa fontu, kolor.
- `PageData`: numer strony, szerokość i wysokość w pt, rotacja, lista `Shape`, lista `TextItem`, liczba obrazów, ostrzeżenia.

## 6. Ekstrakcja (PyMuPDF)

> **Uwaga dla implementującego:** poniższy opis struktur danych pochodzi z dokumentacji PyMuPDF, ale może się różnić między wersjami. Przed implementacją wypisz rzeczywisty wynik `get_drawings()` i `get_text("dict")` dla testowego PDF w zainstalowanej wersji i trzymaj się tego, co faktycznie zwraca biblioteka.

### Ścieżki — `page.get_drawings()`

Zwraca listę słowników. Istotne klucze: `items`, `type` (`"s"` obrys, `"f"` wypełnienie, `"fs"` oba), `color`, `fill`, `width`, `dashes`, `closePath`, `even_odd`, `fill_opacity`, `stroke_opacity` i — w nowszych wersjach — `layer` (nazwa warstwy OCG).

Elementy `items`:

- `("l", p1, p2)` → `LineSeg`
- `("c", p1, p2, p3, p4)` → `CubicSeg`
- `("re", rect, orientation)` → 4 odcinki, zamknięte
- `("qu", quad)` → 4 odcinki, zamknięte

Jeden słownik może zawierać kilka podścieżek: nowa podścieżka zaczyna się, gdy początek elementu nie pokrywa się (z tolerancją) z końcem poprzedniego.

### Tekst — `page.get_text("dict")`

Struktura: bloki → linie → spany. Ze spanu bierzemy `text`, `origin` (punkt na linii bazowej), `size`, `font`, `color` (sRGB jako int). Z linii bierzemy `dir` = (cos, sin) — kierunek tekstu w układzie PDF (oś Y w dół). Po odbiciu osi Y kąt w DXF = `-degrees(atan2(sin, cos))`.

Bloki obrazów (typ 1) oraz `page.get_images()` służą do wykrywania stron rastrowych.

### Wykrywanie skanów

Jeśli strona ma obrazy i (prawie) nie ma ścieżek ani tekstu — oznacz ją jako rastrową, dodaj ostrzeżenie i pomiń. Jeśli żadna strona nie ma wektorów, program kończy się kodem 3 z komunikatem, że PDF wygląda na skan i wymaga wektoryzacji (np. potrace / dedykowany program).

### Strony obrócone (`/Rotate`)

Sprawdź testem, w jakim układzie PyMuPDF zwraca współrzędne `get_drawings()` i `get_text()` dla stron z `page.rotation != 0`, i w razie potrzeby zastosuj `page.rotation_matrix`. **Kryterium:** DXF ma wyglądać tak, jak strona wyświetlana w przeglądarce PDF.

## 7. Transformacja współrzędnych i jednostki

- PDF (PyMuPDF): początek w lewym górnym rogu, oś Y w dół, jednostka = 1 pt = 1/72 cala.
- DXF: oś Y w górę.
- Wzór: `x_dxf = x * k`, `y_dxf = (H - y) * k`, gdzie `H` to wysokość strony w pt, a `k = współczynnik_jednostki * skala`.
- Jednostki (`--units`): `mm` (domyślnie, 1 pt = 25.4/72 mm), `cm`, `m`, `in`, `pt`. Ustaw `$INSUNITS` w nagłówku DXF (mm = 4, cm = 5, m = 6, in = 1, bez jednostek = 0).
- Skala (`--scale N`): rysunek w skali 1:N → wszystkie współrzędne mnożymy przez N, żeby w DXF były wymiary rzeczywiste. Przykład: arkusz w skali 1:100 i `--units mm` → odcinek 10 mm na papierze = 1000 mm w DXF.
- **Grubość linii nie podlega skali** (to cecha wydruku): pt → mm → najbliższa dopuszczalna wartość lineweight DXF w setnych mm (lista w `ezdxf.lldxf.const.VALID_DXF_LINEWEIGHTS`).
- Wysokość tekstu podlega skali (tekst leży w przestrzeni modelu).

## 8. Mapowanie na encje DXF

| Źródło w PDF | Encja DXF |
|---|---|
| Otwarta podścieżka z 1 odcinka | `LINE` |
| Otwarta podścieżka z wielu odcinków | `LWPOLYLINE` (otwarta) |
| Zamknięta podścieżka z odcinków | `LWPOLYLINE` (zamknięta) |
| Podścieżka z krzywymi, `--curves spline` (domyślnie) | `SPLINE` przez `ezdxf.path` (`render_splines_and_polylines`) |
| Podścieżka z krzywymi, `--curves polyline` | `LWPOLYLINE` po spłaszczeniu z tolerancją `--flatten-tol` (domyślnie 0.01 mm) |
| 4 krzywe Béziera tworzące okrąg | `CIRCLE` (gdy `--detect-arcs`, domyślnie włączone) |
| Krzywa Béziera przybliżająca łuk ≤ 90° | `ARC` (gdy `--detect-arcs`) |
| Wypełnienie (`type` `f` / `fs`) | `HATCH` typu SOLID (+ obrys przy `fs`) zależnie od `--fills` |
| Span tekstu | `TEXT` |

Szczegóły:

- **Ścieżki budujemy przez `ezdxf.path.Path`** (`line_to`, `curve4_to`, `close`) — to wspólna abstrakcja dla linii, spline'ów, polilinii i kreskowań.
- **Kolory:** ustaw prawdziwy kolor (`entity.rgb`) oraz najbliższy kolor ACI. **Czarny mapuj na ACI 7** (biały/czarny zależnie od tła), inaczej czarne linie znikną na czarnym tle w CAD.
- **Wypełnienia (`--fills hatch|outline|ignore`, domyślnie `hatch`):** białe wypełnienia pokrywające prawie całą stronę (tło) pomijaj zawsze. Respektuj `even_odd` przy tworzeniu HATCH.
- **Warstwy (`--layers by-color|by-ocg|single`, domyślnie `by-color`):** `by-color` → warstwy typu `PDF_FF0000`; `by-ocg` → nazwy warstw z PDF, jeśli backend je zwraca (z fallbackiem na `by-color`); `single` → jedna warstwa `PDF`. Nazwy oczyść ze znaków niedozwolonych w DXF (`<>/\":;?*|=` i backtick).
- **Linie przerywane:** jeśli `dashes` nie jest puste, utwórz własny typ linii z wzoru PDF (przeliczonego na jednostki DXF) przez `doc.linetypes.add(...)`, z cache, żeby nie dublować identycznych wzorów.
- **Tekst:** punkt wstawienia `TEXT` to lewy koniec linii bazowej — odpowiada `origin` spanu. Wysokość = rozmiar fontu × `k` × `--text-height-factor` (domyślnie 0.7, bo wysokość tekstu w DXF to w przybliżeniu wysokość wielkich liter). Styl tekstu z fontem TTF obsługującym polskie znaki (np. `arial.ttf`). DXF R2010 zapisuje tekst w UTF-8 — **znaki „ąćęłńóśźż” muszą przejść bez zmian.** Opcje: `--no-text`, `--merge-text` (łączenie spanów z jednej linii o tym samym stylu).

## 9. Postprocessing

- Usuwanie odcinków o zerowej długości.
- **Deduplikacja:** eksporty z CAD często rysują te same linie dwa razy. Usuwaj identyczne odcinki (z tolerancją, niezależnie od kierunku) o tym samym stylu.
- **Wykrywanie okręgów i łuków** (`--detect-arcs`, domyślnie włączone) z tolerancją względną.
- **Łączenie** (`--join`, domyślnie wyłączone): sklejanie odcinków o wspólnych końcach i tym samym stylu w polilinie.
- Zaokrąglanie współrzędnych do ~1e-6 jednostki, żeby uniknąć szumu numerycznego.

## 10. CLI

```
pdf2dxf INPUT.pdf [-o OUT.dxf | -o KATALOG/]
        [--pages 1,3-5] [--single-file]
        [--units mm|cm|m|in|pt] [--scale N]
        [--curves spline|polyline] [--flatten-tol 0.01]
        [--layers by-color|by-ocg|single]
        [--fills hatch|outline|ignore]
        [--no-text] [--merge-text] [--text-height-factor 0.7]
        [--detect-arcs | --no-detect-arcs] [--join]
        [--dxf-version R2010]
        [--preview]
        [--dwg] [--dwg-version R2018]
        [-v | --verbose]
```

- Wiele stron: domyślnie jeden plik na stronę (`nazwa_p1.dxf`, `nazwa_p2.dxf`, …). `--single-file` układa strony obok siebie w jednym DXF z odstępem.
- `--preview`: zapisuje obok DXF plik PNG wyrenderowany z DXF (do szybkiej kontroli wzrokowej).
- Na końcu raport: dla każdej strony liczba encji wg typu, liczba usuniętych duplikatów, ostrzeżenia.
- Kody wyjścia: `0` OK, `1` błąd, `2` złe argumenty, `3` brak danych wektorowych (skan).
- Działa też `python -m pdf2dxf`.

## 11. DWG (faza opcjonalna)

- Konwersja gotowego DXF → DWG przez **ODA File Converter** (darmowy program Open Design Alliance, trzeba go pobrać i zainstalować osobno).
- Użyj `ezdxf.addons.odafc` (sprawdzenie, czy konwerter jest zainstalowany, i konwersja/eksport do DWG).
- Gdy konwertera nie ma: czytelny komunikat, gdzie go pobrać i jak wskazać ścieżkę; DXF i tak zostaje zapisany.
- LibreDWG (`dxf2dwg`) — tylko jako wzmianka w README; zapis DWG jest tam eksperymentalny.

## 12. Testy

Testowe PDF-y generuj w fixture'ach przez PyMuPDF (`draw_line`, `draw_rect`, `draw_circle`, `draw_bezier`, `insert_text`, `insert_image`, `set_rotation`), żeby geometria była znana co do liczby. Nie commituj binarnych PDF-ów poza ewentualnymi przykładami w `samples/`.

Minimalny zestaw przypadków:

1. Linia (100, 100)–(200, 100) pt → `LINE` długości 35.2778 mm (±1e-3), z poprawnie odbitą osią Y.
2. Prostokąt → zamknięta `LWPOLYLINE` z 4 wierzchołkami.
3. Okrąg r = 50 pt → `CIRCLE` r = 17.639 mm przy `--detect-arcs`; `SPLINE` przy `--no-detect-arcs`; `LWPOLYLINE` przy `--curves polyline`.
4. Krzywa Béziera → `SPLINE` z poprawnymi punktami końcowymi.
5. Tekst „Zażółć gęślą jaźń” → `TEXT` z identycznym ciągiem znaków. (Uwaga: wbudowana Helvetica w PDF może nie mieć polskich znaków — do fixture'a użyj fontu Unicode, np. pliku TTF lub fontów z pakietu `pymupdf-fonts`.)
6. Czerwona linia → `rgb == (255, 0, 0)` i warstwa `PDF_FF0000`; czarna → ACI 7.
7. `--scale 100` → wymiary × 100; `--units in` → poprawne przeliczenie i `$INSUNITS`.
8. Linia przerywana → własny typ linii przypisany do encji.
9. Wypełniony prostokąt → `HATCH` SOLID.
10. Strona obrócona o 90° → geometria zgodna z wyglądem strony w przeglądarce.
11. Strona z samym obrazem → ostrzeżenie i kod wyjścia 3.
12. Dwie identyczne linie → w DXF jedna.
13. PDF wielostronicowy → osobne pliki, `--pages` działa, `--single-file` działa.
14. Każdy wygenerowany DXF: `ezdxf.readfile()` otwiera go ponownie, `doc.audit()` nie zgłasza błędów.
15. (Opcjonalny test wizualny) Rasteryzacja strony PDF i PNG z DXF w tej samej rozdzielczości, porównanie masek ciemnych pikseli (np. IoU > 0.9) — z tolerancją, oznaczony jako wolny.

## 13. Fazy realizacji

Każda faza kończy się zielonymi testami i krótkim podsumowaniem.

- **Faza 0 — szkielet:** `pyproject.toml` (z entry pointem `pdf2dxf` i extras `[preview]`, `[dev]`), środowisko wirtualne, struktura katalogów, `pdf2dxf --help` działa, pusty test przechodzi.
  *Akceptacja:* `pytest` przechodzi, `pdf2dxf --help` wyświetla opcje.
- **Faza 1 — linie i prostokąty:** model, backend PyMuPDF (tylko ścieżki), transformacja, writer z `LINE`/`LWPOLYLINE`, podstawowe CLI.
  *Akceptacja:* testy 1, 2, 7, 14.
- **Faza 2 — krzywe i styl:** Béziery (`spline`/`polyline`), kolory, grubości, warstwy, linie przerywane, wypełnienia.
  *Akceptacja:* testy 3 (bez wykrywania okręgów), 4, 6, 8, 9.
- **Faza 3 — tekst.**
  *Akceptacja:* test 5, tekst obrócony ma poprawny kąt.
- **Faza 4 — postprocessing i strony:** deduplikacja, okręgi/łuki, `--join`, wiele stron, strony obrócone, wykrywanie skanów, raport, kody wyjścia.
  *Akceptacja:* testy 3 (pełny), 10–13.
- **Faza 5 — podgląd i weryfikacja:** `--preview`, opcjonalny test wizualny, README z instrukcją, przykładami i znanymi ograniczeniami. Jeśli w `samples/` są PDF-y użytkownika, przepuść je przez konwerter i pokaż raporty.
  *Akceptacja:* test 15 (jeśli zaimplementowany), README kompletne.
- **Faza 6 (opcjonalna) — DWG** przez ODA File Converter.
- **Faza 7 (opcjonalna) — proste GUI** w tkinter: wybór pliku, podstawowe opcje (jednostki, skala, krzywe), przycisk „Konwertuj”, log.

## 14. Zasady pracy

- Nie zgaduj API PyMuPDF ani ezdxf. Jeśli nie masz pewności, sprawdź w zainstalowanej wersji (`help()`, `dir()`, krótki skrypt) i dopiero wtedy pisz kod.
- Po każdej fazie uruchom pełne testy; nie przechodź dalej z niezaliczonymi testami.
- Kod z type hints i docstringami; funkcje krótkie i testowalne.
- Jeśli repozytorium jest pod gitem — commit po każdej fazie.
- Decyzje odbiegające od tej specyfikacji zapisuj w README w sekcji „Decyzje projektowe” z krótkim uzasadnieniem.

## 15. Znane ograniczenia (do README)

- PDF to „spłaszczony” rysunek: nie ma w nim bloków, wymiarów asocjacyjnych ani informacji o tym, które linie tworzą jeden obiekt.
- Skalę rysunku musi podać użytkownik (`--scale`) — PDF jej nie przechowuje.
- Wzory kreskowania przychodzą jako setki lub tysiące pojedynczych linii.
- Fonty są zastępowane jednym fontem TTF; położenie i wysokość tekstu są przybliżone.
- Tekst zamieniony w PDF na krzywe przychodzi jako geometria.
- Skany wymagają wektoryzacji, której to narzędzie nie robi.
