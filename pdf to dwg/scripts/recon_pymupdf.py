"""Skrypt rozpoznawczy: jaka jest rzeczywista struktura wyników PyMuPDF.

Generuje testowy PDF (linia, prostokąt, okrąg, Bézier, tekst z polskimi
znakami, linia przerywana, wypełnienia, OCG, even-odd, strona obrócona,
strona z obrazem) i wypisuje wynik ``page.get_drawings()`` oraz
``page.get_text("dict")``.

Użycie:  python scripts/recon_pymupdf.py [katalog_wyjściowy]
"""

from __future__ import annotations

import sys
from pathlib import Path
from pprint import pformat

import pymupdf

POLISH = "Zażółć gęślą jaźń"


def build_pdf(path: Path) -> None:
    doc = pymupdf.open()
    ocg = doc.add_ocg("Warstwa_A")

    # --- strona 1: wszystko na raz -------------------------------------
    page = doc.new_page(width=595, height=842)
    page.draw_line((100, 100), (200, 100), color=(1, 0, 0), width=1)
    page.draw_rect(pymupdf.Rect(50, 200, 150, 260), color=(0, 0, 0), width=0.5)
    page.draw_circle((300, 300), 50, color=(0, 0, 1), width=1)
    page.draw_bezier((50, 400), (100, 350), (150, 450), (200, 400), color=(0, 0.5, 0))
    page.draw_line((50, 500), (250, 500), color=(0, 0, 0), dashes="[6 3] 0", width=0.7)
    page.draw_rect(pymupdf.Rect(300, 450, 400, 500), color=None, fill=(0, 0, 1))
    page.draw_rect(pymupdf.Rect(420, 450, 520, 500), color=(1, 0, 0), fill=(1, 1, 0))
    page.draw_quad(pymupdf.Rect(300, 550, 380, 600).quad, color=(0, 0, 0))
    page.draw_line((50, 700), (150, 700), color=(0, 0, 0), oc=ocg)

    # dwie rozłączne podścieżki w jednym finish() + even-odd
    sh = page.new_shape()
    sh.draw_rect(pymupdf.Rect(420, 550, 520, 650))
    sh.draw_rect(pymupdf.Rect(440, 570, 500, 630))
    sh.finish(color=(0, 0, 0), fill=(0.5, 0.5, 0.5), even_odd=True)
    sh.commit()

    sh = page.new_shape()  # dwie otwarte, niepołączone linie w jednej ścieżce
    sh.draw_line((50, 750), (100, 750))
    sh.draw_line((120, 760), (170, 760))
    sh.finish(color=(0, 0, 0), closePath=False)
    sh.commit()

    font = pymupdf.Font("notos")  # Noto Sans z pakietu pymupdf-fonts
    page.insert_font(fontname="notos", fontbuffer=font.buffer)
    page.insert_text((50, 150), POLISH, fontname="notos", fontsize=12, color=(0, 0, 0))
    page.insert_text((400, 150), "Obrot90", fontname="notos", fontsize=10, rotate=90)
    # dowolny kąt przez morph (30 stopni wokół punktu wstawienia)
    p0 = pymupdf.Point(250, 780)
    page.insert_text(p0, "Kat30", fontname="notos", fontsize=10,
                     morph=(p0, pymupdf.Matrix(-30)))

    # --- strona 2: obrócona o 90 stopni --------------------------------
    page = doc.new_page(width=595, height=842)
    page.draw_line((100, 100), (200, 100), color=(1, 0, 0))
    page.insert_font(fontname="notos", fontbuffer=font.buffer)
    page.insert_text((100, 200), "Rot", fontname="notos", fontsize=12)
    page.set_rotation(90)

    # --- strona 3: sam obraz --------------------------------------------
    page = doc.new_page(width=595, height=842)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), False)
    pix.clear_with(200)
    page.insert_image(pymupdf.Rect(100, 100, 400, 400), pixmap=pix)

    doc.save(path)


def dump(path: Path) -> str:
    out: list[str] = [f"PyMuPDF {pymupdf.VersionBind} (MuPDF {pymupdf.VersionFitz})"]
    doc = pymupdf.open(path)
    out.append(f"OCGs: {doc.get_ocgs()}")
    for page in doc:
        out.append("=" * 78)
        out.append(
            f"page {page.number}: rotation={page.rotation} rect={page.rect} "
            f"mediabox={page.mediabox} cropbox={page.cropbox}"
        )
        out.append(f"rotation_matrix={page.rotation_matrix}")
        out.append(f"derotation_matrix={page.derotation_matrix}")
        out.append(f"get_images()={page.get_images()}")
        out.append("--- get_drawings() ---")
        for d in page.get_drawings():
            out.append(pformat(d, width=110, sort_dicts=True))
        out.append("--- get_text('dict') (bez binarnych obrazów) ---")
        td = page.get_text("dict")
        out.append(f"keys: {sorted(td)} width={td['width']} height={td['height']}")
        for b in td["blocks"]:
            if b["type"] == 1:
                b = {k: v for k, v in b.items() if k != "image"}
                out.append("IMAGE BLOCK: " + pformat(b, width=110))
                continue
            out.append(f"TEXT BLOCK keys={sorted(b)} bbox={b['bbox']}")
            for ln in b["lines"]:
                out.append(f"  LINE keys={sorted(ln)} dir={ln['dir']} wmode={ln['wmode']}")
                for sp in ln["spans"]:
                    out.append("    SPAN " + pformat(sp, width=110, sort_dicts=True))
    return "\n".join(out)


def main() -> None:
    outdir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    outdir.mkdir(parents=True, exist_ok=True)
    pdf = outdir / "recon.pdf"
    build_pdf(pdf)
    text = dump(pdf)
    (outdir / "recon_output.txt").write_text(text, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
