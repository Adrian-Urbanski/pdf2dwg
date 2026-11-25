"""Proste okno (tkinter): dodaj PDF → „Konwertuj” → powstaje DWG (i opcjonalnie DXF).

Uruchamianie: ``pdf2dxf-gui`` albo ``python -m pdf2dxf.gui [pliki.pdf]``.
Pliki podane w wierszu poleceń (np. PDF upuszczony na ikonę .exe) trafiają
na listę i czekają na „Konwertuj”. Po prawej stronie okna jest podgląd
zaznaczonego pliku. Przeciąganie plików do okna wymaga pakietu
``tkinterdnd2`` — bez niego działa wybór pliku przyciskiem.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import traceback
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdf2dxf import __version__
from pdf2dxf.backends import open_pdf
from pdf2dxf.cli import format_report
from pdf2dxf.converter import ConversionError, ConvertOptions, UsageError, convert
from pdf2dxf.dwg import DWG_VERSIONS, ODA_URL, find_converter

UNIT_CHOICES = ("mm", "cm", "m", "in")
CURVE_CHOICES = {"spline": "SPLINE (gładkie krzywe)", "polyline": "polilinie (np. dla CNC)"}


@dataclass
class GuiSettings:
    """Ustawienia konwersji wybrane w oknie."""

    units: str = "mm"
    scale: float = 1.0
    curves: str = "spline"
    keep_dxf: bool = False
    dwg_version: str = "R2018"

    def options(self) -> ConvertOptions:
        return ConvertOptions(
            units=self.units, scale=self.scale, curves=self.curves,
            dwg=True, dwg_version=self.dwg_version,
        )


@dataclass
class JobResult:
    """Wynik konwersji jednego pliku do pokazania w logu."""

    pdf: Path
    text: str
    ok: bool
    outputs: list[Path]


def parse_scale(text: str) -> float:
    """Skala z pola tekstowego: ``50``, ``1:50`` albo ``1/50`` → 50.

    Raises:
        ValueError: gdy zapis jest niepoprawny albo skala nie jest dodatnia.
    """
    t = text.strip().replace(",", ".").replace(" ", "")
    for sep in (":", "/"):
        if sep in t:
            left, right = t.split(sep, 1)
            value = float(right) / float(left)
            break
    else:
        value = float(t)
    if not value > 0:
        raise ValueError(f"skala musi być dodatnia: {text!r}")
    return value


def pdf_paths(items: list[str]) -> tuple[list[Path], list[str]]:
    """Rozdziela upuszczone/wybrane ścieżki na pliki PDF i odrzucone pozycje."""
    pdfs: list[Path] = []
    rejected: list[str] = []
    for item in items:
        path = Path(item)
        if path.is_file() and path.suffix.lower() == ".pdf":
            pdfs.append(path)
        else:
            rejected.append(item)
    return pdfs, rejected


def run_job(pdf: Path, settings: GuiSettings) -> JobResult:
    """Konwertuje jeden PDF (DXF → DWG). DXF jest usuwany, gdy powstał DWG i nie
    zaznaczono „zachowaj DXF”. Nigdy nie rzuca wyjątku — błąd trafia do tekstu."""
    try:
        report = convert(pdf, None, settings.options())
    except (ConversionError, UsageError) as exc:
        return JobResult(pdf, f"{pdf.name}: błąd: {exc}", False, [])
    except Exception:  # błąd programu — pokaż szczegóły zamiast zamykać okno
        return JobResult(pdf, f"{pdf.name}: nieoczekiwany błąd:\n{traceback.format_exc()}",
                         False, [])
    lines = [format_report(report)]
    outputs = list(report.dwg_outputs)
    if report.dwg_outputs and not settings.keep_dxf:
        for dxf in report.outputs:
            if dxf.with_suffix(".dwg") in report.dwg_outputs:
                dxf.unlink(missing_ok=True)
    else:
        outputs += report.outputs
        if report.outputs and not report.dwg_outputs:
            lines.append("  zapisano tylko DXF")
    for err in report.dwg_errors:
        lines.append(f"  błąd DWG: {err}")
    if report.no_vector_data:
        lines.append("  brak danych wektorowych — PDF wygląda na skan albo jest pusty")
    ok = bool(report.dwg_outputs) and not report.dwg_errors
    return JobResult(pdf, "\n".join(lines), ok, outputs)


# ---------------------------------------------------------------------------
# okno
# ---------------------------------------------------------------------------


def _make_root() -> tuple[Any, bool]:
    """Okno główne; z obsługą przeciągania plików, jeśli dostępne jest tkinterdnd2."""
    try:
        from tkinterdnd2 import TkinterDnD

        return TkinterDnD.Tk(), True
    except Exception:  # brak pakietu albo biblioteki tkdnd
        import tkinter as tk

        return tk.Tk(), False


@dataclass
class FileEntry:
    """Plik na liście do konwersji."""

    path: Path
    status: str = "pending"  # pending | working | ok | error


_STATUS_MARK = {"pending": "•", "working": "…", "ok": "✓", "error": "✗"}
_STATUS_COLOR = {"pending": "#222222", "working": "#1d4ed8", "ok": "#1a7f37", "error": "#b42318"}
_DROP_BG = "#f4f6f8"
_DROP_BG_ACTIVE = "#dbeafe"


class App:
    """Okno konwertera: lista plików i ustawienia po lewej, podgląd po prawej,
    log na dole. Konwersja startuje przyciskiem „Konwertuj”."""

    def __init__(self, root: Any, dnd: bool) -> None:
        import tkinter as tk
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText

        self.root = root
        self.dnd = dnd
        self.files: list[FileEntry] = []
        self.jobs: queue.Queue[tuple[Path, GuiSettings]] = queue.Queue()
        self.results: queue.Queue[JobResult | str] = queue.Queue()
        self.busy = False
        self.last_folder: Path | None = None
        self.preview_path: Path | None = None
        self.preview_page = 0
        self.preview_pages = 0
        self._photo: Any = None
        self._resize_job: str | None = None

        root.title(f"PDF → DWG  (pdf2dxf {__version__})")
        root.minsize(900, 620)
        root.geometry("1040x720")
        root.columnconfigure(0, weight=1, uniform="half")
        root.columnconfigure(1, weight=1, uniform="half")
        root.rowconfigure(0, weight=3)  # lista plików / podgląd rosną najbardziej
        root.rowconfigure(3, weight=1)  # log
        root.report_callback_exception = self._callback_error

        # --- lewa kolumna: pliki ------------------------------------------------------
        files_box = ttk.LabelFrame(root, text="Pliki PDF do konwersji")
        files_box.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=(10, 5))
        files_box.columnconfigure(0, weight=1)
        files_box.rowconfigure(0, weight=1)
        self.listbox = tk.Listbox(files_box, activestyle="none", font=("Segoe UI", 10),
                                  selectmode="extended", bg=_DROP_BG, relief="flat",
                                  highlightthickness=1, highlightcolor="#93c5fd")
        self.listbox.grid(row=0, column=0, columnspan=3, sticky="nsew", padx=6, pady=(6, 4))
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._on_select())
        hint = ("Upuść tutaj pliki PDF\nalbo kliknij, aby wybrać" if dnd
                else "Kliknij, aby wybrać pliki PDF")
        self.hint = tk.Label(self.listbox, text=hint, font=("Segoe UI", 13), bg=_DROP_BG,
                             fg="#555555", cursor="hand2")
        self.hint.bind("<Button-1>", lambda _e: self.choose_files())
        self.add_btn = ttk.Button(files_box, text="Dodaj PDF…", command=self.choose_files)
        self.add_btn.grid(row=1, column=0, sticky="w", padx=6, pady=(0, 6))
        self.remove_btn = ttk.Button(files_box, text="Usuń zaznaczone", command=self.remove_selected)
        self.remove_btn.grid(row=1, column=1, sticky="e", pady=(0, 6))
        self.clear_btn = ttk.Button(files_box, text="Wyczyść", command=self.clear_files)
        self.clear_btn.grid(row=1, column=2, sticky="e", padx=6, pady=(0, 6))

        # --- lewa kolumna: ustawienia --------------------------------------------------
        box = ttk.LabelFrame(root, text="Ustawienia")
        box.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=5)
        self.units = tk.StringVar(value="mm")
        self.scale = tk.StringVar(value="1")
        self.curves = tk.StringVar(value="spline")
        self.keep_dxf = tk.BooleanVar(value=False)
        self.dwg_version = tk.StringVar(value="R2018")
        ttk.Label(box, text="Jednostki:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(box, textvariable=self.units, values=UNIT_CHOICES, width=6,
                     state="readonly").grid(row=0, column=1, sticky="w")
        ttk.Label(box, text="Skala  1 :").grid(row=0, column=2, sticky="e", padx=(14, 4))
        ttk.Entry(box, textvariable=self.scale, width=8).grid(row=0, column=3, sticky="w")
        ttk.Label(box, text="Wersja DWG:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(box, textvariable=self.dwg_version, values=DWG_VERSIONS, width=7,
                     state="readonly").grid(row=1, column=1, sticky="w")
        ttk.Label(box, text="Krzywe:").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        for i, (value, label) in enumerate(CURVE_CHOICES.items()):
            ttk.Radiobutton(box, text=label, variable=self.curves, value=value).grid(
                row=2 + i, column=1, columnspan=3, sticky="w")
        ttk.Checkbutton(box, text="Zachowaj też plik DXF", variable=self.keep_dxf).grid(
            row=4, column=0, columnspan=4, sticky="w", padx=6, pady=(2, 6))

        # --- prawa kolumna: podgląd ------------------------------------------------------
        pv = ttk.LabelFrame(root, text="Podgląd")
        pv.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(5, 10), pady=(10, 5))
        pv.columnconfigure(1, weight=1)
        pv.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(pv, bg="#9ca3af", highlightthickness=0, width=380, height=380)
        self.canvas.grid(row=0, column=0, columnspan=3, sticky="nsew", padx=6, pady=(6, 4))
        self.canvas.bind("<Configure>", lambda _e: self._schedule_preview())
        self.prev_btn = ttk.Button(pv, text="◀", width=3, command=lambda: self.turn_page(-1))
        self.prev_btn.grid(row=1, column=0, padx=6, pady=(0, 6))
        self.page_label = ttk.Label(pv, text="", anchor="center")
        self.page_label.grid(row=1, column=1, sticky="ew", pady=(0, 6))
        self.next_btn = ttk.Button(pv, text="▶", width=3, command=lambda: self.turn_page(1))
        self.next_btn.grid(row=1, column=2, padx=6, pady=(0, 6))

        # --- status ODA, log, przyciski ----------------------------------------------------
        oda = ttk.Frame(root)
        oda.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10)
        self.oda_label = ttk.Label(oda, text="")
        self.oda_label.pack(side="left")
        self.oda_link = ttk.Button(oda, text="Pobierz ODA File Converter",
                                   command=lambda: webbrowser.open(ODA_URL))
        self.log = ScrolledText(root, height=6, font=("Consolas", 9), state="disabled",
                                wrap="word")
        self.log.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=10, pady=6)
        bottom = ttk.Frame(root)
        bottom.grid(row=4, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
        self.status = ttk.Label(bottom, text="Dodaj pliki PDF i kliknij „Konwertuj”.")
        self.status.pack(side="left")
        style = ttk.Style(root)
        style.configure("Convert.TButton", font=("Segoe UI", 11, "bold"), padding=(18, 6))
        self.convert_btn = ttk.Button(bottom, text="Konwertuj", style="Convert.TButton",
                                      command=self.convert_files)
        self.convert_btn.pack(side="right")
        self.open_btn = ttk.Button(bottom, text="Otwórz folder z wynikiem",
                                   command=self.open_folder, state="disabled")
        self.open_btn.pack(side="right", padx=8)

        if dnd:
            from tkinterdnd2 import DND_FILES

            for widget in (files_box, self.listbox, self.hint, self.canvas):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
                widget.dnd_bind("<<DropEnter>>", lambda e: self._highlight(True) or e.action)
                widget.dnd_bind("<<DropLeave>>", lambda e: self._highlight(False) or e.action)

        self.refresh_oda()
        self._refresh_list()
        self.show_preview()
        root.after(100, self._poll)

    # -- lista plików -----------------------------------------------------------------------

    def choose_files(self) -> None:
        from tkinter import filedialog

        names = filedialog.askopenfilenames(
            title="Wybierz pliki PDF", filetypes=[("Pliki PDF", "*.pdf"), ("Wszystkie", "*.*")])
        if names:
            self.add_files(list(names))

    def add_files(self, items: list[str]) -> None:
        """Dodaje pliki do listy (bez konwersji). Gotowe (✓) pliki znikają z listy,
        gdy dodawane są nowe."""
        pdfs, rejected = pdf_paths(items)
        for item in rejected:
            self.write(f"Pominięto (to nie jest plik PDF): {item}")
        if not pdfs:
            return
        if not self.busy:
            self.files = [e for e in self.files if e.status != "ok"]
        known = {e.path.resolve() for e in self.files}
        first_new: Path | None = None
        for pdf in pdfs:
            if pdf.resolve() not in known:
                self.files.append(FileEntry(pdf))
                known.add(pdf.resolve())
                first_new = first_new or pdf
        self._refresh_list()
        target = first_new or pdfs[0]
        self._select(target)
        self.show_preview(target, 0)
        self.status.configure(text="Kliknij „Konwertuj”, aby zapisać DWG.")

    def remove_selected(self) -> None:
        if self.busy:
            return
        selected = set(self.listbox.curselection())
        self.files = [e for i, e in enumerate(self.files) if i not in selected]
        self._refresh_list()
        if self.preview_path not in {e.path for e in self.files}:
            self.show_preview(self.files[0].path if self.files else None, 0)

    def clear_files(self) -> None:
        if self.busy:
            return
        self.files.clear()
        self._refresh_list()
        self.show_preview(None)

    def _refresh_list(self) -> None:
        selected = {self.files[i].path for i in self.listbox.curselection()
                    if i < len(self.files)} if self.listbox.size() == len(self.files) else set()
        self.listbox.delete(0, "end")
        for i, entry in enumerate(self.files):
            self.listbox.insert("end", f" {_STATUS_MARK[entry.status]}  {entry.path.name}")
            self.listbox.itemconfig(i, foreground=_STATUS_COLOR[entry.status])
            if entry.path in selected:
                self.listbox.selection_set(i)
        if self.files:
            self.hint.place_forget()
        else:
            self.hint.place(relx=0.5, rely=0.5, anchor="center")
        self._update_buttons()

    def _select(self, path: Path) -> None:
        self.listbox.selection_clear(0, "end")
        for i, entry in enumerate(self.files):
            if entry.path == path:
                self.listbox.selection_set(i)
                self.listbox.see(i)

    def _on_select(self) -> None:
        sel = self.listbox.curselection()
        if sel and sel[0] < len(self.files) and self.files[sel[0]].path != self.preview_path:
            self.show_preview(self.files[sel[0]].path, 0)

    def _update_buttons(self) -> None:
        idle = "disabled" if self.busy else "normal"
        self.convert_btn.configure(state="normal" if self.files and not self.busy else "disabled")
        for btn in (self.remove_btn, self.clear_btn):
            btn.configure(state=idle if self.files else "disabled")

    # -- konwersja ----------------------------------------------------------------------------

    def settings(self) -> GuiSettings:
        try:
            scale = parse_scale(self.scale.get())
        except (ValueError, ZeroDivisionError):
            raise ValueError(f"niepoprawna skala „{self.scale.get()}” — wpisz np. 50 "
                             "albo 1:50") from None
        return GuiSettings(units=self.units.get(), scale=scale, curves=self.curves.get(),
                           keep_dxf=self.keep_dxf.get(), dwg_version=self.dwg_version.get())

    def convert_files(self) -> None:
        """Konwertuje pliki z listy: oczekujące i z błędem; gdy wszystkie są gotowe —
        wszystkie ponownie (np. po zmianie skali)."""
        if self.busy:
            return
        if not self.files:
            self.write("Najpierw dodaj pliki PDF.")
            return
        try:
            settings = self.settings()
        except ValueError as exc:
            self.write(f"Błąd: {exc}")
            return
        todo = [e for e in self.files if e.status != "ok"] or list(self.files)
        for entry in todo:
            entry.status = "working"
            self.jobs.put((entry.path, settings))
        self.busy = True
        self._refresh_list()
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        while True:
            try:
                pdf, settings = self.jobs.get_nowait()
            except queue.Empty:
                self.results.put("done")
                return
            self.results.put(f"Konwertuję: {pdf.name} …")
            self.results.put(run_job(pdf, settings))

    def _poll(self) -> None:
        try:
            while True:
                item = self.results.get_nowait()
                if item == "done":
                    self.busy = False
                    ok = sum(e.status == "ok" for e in self.files)
                    bad = sum(e.status == "error" for e in self.files)
                    self.status.configure(
                        text=f"Gotowe: {ok} plik(ów) skonwertowano" + (f", błędy: {bad}" if bad
                                                                         else "."))
                    self._refresh_list()
                elif isinstance(item, str):
                    self.status.configure(text=item)
                    self.write(item)
                else:
                    self.write(item.text + "\n")
                    for entry in self.files:
                        if entry.path == item.pdf:
                            entry.status = "ok" if item.ok else "error"
                    if item.outputs:
                        self.last_folder = item.outputs[0].parent
                        self.open_btn.configure(state="normal")
                    self._refresh_list()
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    # -- podgląd ------------------------------------------------------------------------------

    def show_preview(self, path: Path | None | str = "", page: int | None = None) -> None:
        """Pokazuje stronę PDF w podglądzie (``path=""`` — odśwież bieżący)."""
        import base64
        import tkinter as tk

        if path != "":
            self.preview_path = path if isinstance(path, Path) or path is None else Path(path)
            self.preview_page = 0
        if page is not None:
            self.preview_page = page
        c = self.canvas
        c.delete("all")
        w, h = max(c.winfo_width(), 50), max(c.winfo_height(), 50)
        if self.preview_path is None:
            self._photo = None
            self.preview_pages = 0
            c.create_text(w / 2, h / 2, text="Podgląd pojawi się\npo dodaniu pliku PDF",
                          fill="white", font=("Segoe UI", 12), justify="center")
            self.page_label.configure(text="")
        else:
            try:
                with open_pdf(self.preview_path) as backend:
                    self.preview_pages = backend.page_count
                    self.preview_page = max(0, min(self.preview_page, self.preview_pages - 1))
                    png = backend.render_png(self.preview_page, w - 16, h - 16)
                self._photo = tk.PhotoImage(data=base64.b64encode(png))
                c.create_image(w / 2, h / 2, image=self._photo, anchor="center")
                self.page_label.configure(
                    text=f"{self.preview_path.name}   —   strona {self.preview_page + 1} "
                         f"z {self.preview_pages}")
            except Exception as exc:  # uszkodzony PDF itp. — podgląd nie jest krytyczny
                self._photo = None
                self.preview_pages = 0
                c.create_text(w / 2, h / 2, text=f"Nie można wyświetlić podglądu:\n{exc}",
                              fill="white", width=w - 20, justify="center")
                self.page_label.configure(text=self.preview_path.name)
        multi = "normal" if self.preview_pages > 1 else "disabled"
        self.prev_btn.configure(state=multi)
        self.next_btn.configure(state=multi)

    def turn_page(self, step: int) -> None:
        if self.preview_pages > 1:
            self.show_preview(page=(self.preview_page + step) % self.preview_pages)

    def _schedule_preview(self) -> None:
        """Odświeża podgląd po zmianie rozmiaru okna (z opóźnieniem, bez migotania)."""
        if self._resize_job is not None:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(150, self._resized)

    def _resized(self) -> None:
        self._resize_job = None
        self.show_preview()

    # -- pozostałe ----------------------------------------------------------------------------

    def refresh_oda(self) -> None:
        exe = find_converter()
        if exe is not None:
            self.oda_label.configure(text=f"ODA File Converter: {exe.parent.name} ✓",
                                     foreground="#1a7f37")
            self.oda_link.pack_forget()
        else:
            self.oda_label.configure(
                text="Brak ODA File Converter — powstanie tylko DXF.", foreground="#b42318")
            self.oda_link.pack(side="left", padx=8)

    def open_folder(self) -> None:
        if self.last_folder is not None and hasattr(os, "startfile"):
            os.startfile(self.last_folder)  # type: ignore[attr-defined]

    def write(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _callback_error(self, exc: type[BaseException], val: BaseException, tb: Any) -> None:
        """Błąd w obsłudze zdarzenia trafia do logu zamiast znikać (brak konsoli)."""
        self.write("Błąd programu:\n" + "".join(traceback.format_exception(exc, val, tb)))

    def _on_drop(self, event: Any) -> str:
        self._highlight(False)
        self.add_files(list(self.root.tk.splitlist(event.data)))
        return event.action

    def _highlight(self, on: bool) -> None:
        color = _DROP_BG_ACTIVE if on else _DROP_BG
        self.listbox.configure(bg=color)
        self.hint.configure(bg=color)


def _dpi_aware() -> None:
    """Ostre czcionki na ekranach z powiększeniem (Windows)."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    """Otwiera okno; pliki z ``argv`` trafiają na listę (konwersja po „Konwertuj”)."""
    files = list(sys.argv[1:] if argv is None else argv)
    _dpi_aware()
    root, dnd = _make_root()
    app = App(root, dnd)
    if files:
        root.after(300, lambda: app.add_files(files))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
