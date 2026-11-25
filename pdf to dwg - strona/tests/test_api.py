"""Testy API strony: przesłanie PDF → zadanie → pobranie wyniku."""

from __future__ import annotations

import io
import sys
import time
import zipfile
from pathlib import Path

import ezdxf
import pymupdf
import pytest
from starlette.testclient import TestClient

from app.main import create_app
from app.options import OptionsError, parse_pages, parse_scale, safe_stem
from app.settings import Settings

FAKE_DWG = Path(__file__).parent / "fake_dwg.py"


def make_pdf(pages: int = 1) -> bytes:
    doc = pymupdf.open()
    for n in range(pages):
        page = doc.new_page(width=595, height=842)
        page.draw_line((50, 50), (300, 50 + n * 10), color=(0, 0, 0), width=1)
        page.draw_rect(pymupdf.Rect(100, 100, 300, 250), color=(1, 0, 0), width=0.5)
        page.draw_circle((400, 400), 50, color=(0, 0, 1))
    data = doc.tobytes()
    doc.close()
    return data


def make_scan_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), False)
    pix.clear_with(200)
    page.insert_image(page.rect, pixmap=pix)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def make_client(tmp_path):
    clients = []

    def factory(**overrides) -> TestClient:
        settings = Settings(**({"data_dir": tmp_path / "data", "workers": 1} | overrides))
        client = TestClient(create_app(settings))
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


def wait(client: TestClient, job_id: str, timeout: float = 60) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        data = client.get(f"/api/jobs/{job_id}").json()
        if data["status"] in ("done", "error"):
            return data
        time.sleep(0.1)
    raise AssertionError("zadanie nie skończyło się na czas")


def upload(client: TestClient, pdf: bytes, name: str = "plan.pdf", **fields) -> dict:
    data = {k: str(v) for k, v in fields.items()}
    resp = client.post("/api/jobs", files={"file": (name, pdf, "application/pdf")}, data=data)
    assert resp.status_code == 202, resp.text
    return wait(client, resp.json()["id"]) | {"id": resp.json()["id"]}


def test_index_and_info(make_client):
    client = make_client(max_upload_mb=40)
    page = client.get("/")
    assert page.status_code == 200 and "content-security-policy" in page.headers
    assert "{{" not in page.text and 'class="mode-dxf"' in page.text
    assert "<h1>Konwerter PDF do DXF</h1>" in page.text and "Pobierz DXF" in page.text
    assert "Pobierz DWG" not in page.text and "do 40 MB" in page.text
    info = client.get("/api/info").json()
    assert info["dwg_available"] is False and info["max_upload_mb"] == 40


def test_index_in_dwg_mode(make_client):
    client = make_client(dwg_engine="command", dwg_command="dxf2dwg {input} {output} {version}")
    page = client.get("/").text
    assert "{{" not in page and 'class="mode-dwg"' in page
    assert "<h1>Konwerter PDF do DWG</h1>" in page and "Pobierz DWG" in page


def test_dxf_conversion(make_client, tmp_path):
    client = make_client()
    job = upload(client, make_pdf(), name="Stół łazienka.pdf", format="dxf", scale="1:50")
    assert job["status"] == "done", job
    result = job["result"]
    assert result["download"]["name"] == "Stół łazienka.dxf"
    assert result["pages"][0]["entities"]["CIRCLE"] == 1
    resp = client.get(f"/api/jobs/{job['id']}/download")
    assert resp.status_code == 200
    assert "filename*=utf-8''St%C3%B3%C5%82" in resp.headers["content-disposition"]
    saved = tmp_path / "wynik.dxf"
    saved.write_bytes(resp.content)
    doc = ezdxf.readfile(saved)
    circle = doc.modelspace().query("CIRCLE")[0]
    assert circle.dxf.radius == pytest.approx(50 * 25.4 / 72 * 50, rel=1e-3)
    assert client.get(f"/api/jobs/{job['id']}/preview.png").headers["content-type"] == "image/png"


def test_multi_page_zip(make_client):
    client = make_client()
    job = upload(client, make_pdf(3), format="dxf", pages="1,3")
    assert job["status"] == "done"
    assert [f["name"] for f in job["result"]["files"]] == ["plan_p1.dxf", "plan_p3.dxf"]
    resp = client.get(f"/api/jobs/{job['id']}/download")
    assert sorted(zipfile.ZipFile(io.BytesIO(resp.content)).namelist()) == [
        "plan_p1.dxf", "plan_p3.dxf"]
    one = client.get(f"/api/jobs/{job['id']}/files/plan_p3.dxf")
    assert one.status_code == 200
    assert client.get(f"/api/jobs/{job['id']}/files/..%2Fjob.json").status_code == 404


def test_dwg_via_command(make_client):
    command = f'"{sys.executable}" "{FAKE_DWG}" {{input}} {{output}} {{version}}'
    client = make_client(dwg_engine="command", dwg_command=command)
    job = upload(client, make_pdf(), format="dwg", dwg_version="R2018")
    assert job["status"] == "done", job
    assert job["result"]["download"]["name"] == "plan.dwg"
    assert client.get(f"/api/jobs/{job['id']}/download").content.startswith(b"FAKE R2018")


def test_dwg_failure_falls_back_to_dxf(make_client):
    command = f'"{sys.executable}" "{FAKE_DWG}" {{input}} {{output}} FAIL'
    client = make_client(dwg_engine="command", dwg_command=command)
    job = upload(client, make_pdf(), format="dwg")
    assert job["status"] == "done"
    assert job["result"]["download"]["name"] == "plan.dxf"
    assert any("DWG" in w for w in job["result"]["warnings"])


def test_rejects_non_pdf_and_dwg_when_unavailable(make_client):
    client = make_client()
    resp = client.post("/api/jobs", files={"file": ("x.pdf", b"hello", "application/pdf")},
                       data={"format": "dxf"})
    assert resp.status_code == 400 and "PDF" in resp.json()["error"]
    resp = client.post("/api/jobs", files={"file": ("x.pdf", make_pdf(), "application/pdf")},
                       data={"format": "dwg"})
    assert resp.status_code == 400 and "DWG" in resp.json()["error"]


def test_upload_size_limit(make_client):
    client = make_client(max_upload_mb=1)
    big = make_pdf() + b"0" * (2 * 1024 * 1024)
    resp = client.post("/api/jobs", files={"file": ("x.pdf", big, "application/pdf")})
    assert resp.status_code == 413


def test_scan_is_reported(make_client):
    client = make_client()
    job = upload(client, make_scan_pdf(), format="dxf")
    assert job["status"] == "error" and "skan" in job["error"]


def test_page_limit(make_client):
    client = make_client(max_pages=2)
    job = upload(client, make_pdf(3), format="dxf")
    assert job["status"] == "error" and "zakres stron" in job["error"]


def test_timeout_kills_job(make_client):
    command = f'"{sys.executable}" "{FAKE_DWG}" {{input}} {{output}} SLEEP'
    client = make_client(job_timeout=2, dwg_engine="command", dwg_command=command)
    job = upload(client, make_pdf(), format="dwg")
    assert job["status"] == "error" and "przerwana" in job["error"]


def test_memory_limit_kills_job(make_client):
    # sam start procesu konwersji (Python + PyMuPDF) zajmuje kilkadziesiąt MB
    client = make_client(job_memory_mb=30)
    job = upload(client, make_pdf(), format="dxf")
    assert job["status"] == "error" and "pamięci" in job["error"]
    assert client.get("/healthz").json()["ok"] is True


def make_malicious_pdf() -> bytes:
    """Jedna linia + JavaScript przy otwarciu, akcja Launch, załączony .exe i tekst z kodami DXF."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_line((50, 50), (300, 300))
    doc.embfile_add("evil.exe", b"MZ" + b"EVILPAYLOAD" * 100, filename="evil.exe")
    js = doc.get_new_xref()
    doc.update_object(js, "<</S/JavaScript/JS(app.alert\\('EVILJS'\\))>>")
    doc.xref_set_key(doc.pdf_catalog(), "OpenAction", f"{js} 0 R")
    annot = doc.get_new_xref()
    doc.update_object(annot, "<</Type/Annot/Subtype/Link/Rect[0 0 99 99]"
                             "/A<</S/Launch/F(cmd.exe)>>>>")
    doc.xref_set_key(page.xref, "Annots", f"[{annot} 0 R]")
    kind, res = doc.xref_get_key(page.xref, "Resources")
    font = "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"
    if kind == "xref":
        doc.xref_set_key(int(res.split()[0]), "Font/F1", font)
    else:
        doc.xref_set_key(page.xref, "Resources/Font/F1", font)
    contents = page.get_contents()[0]
    doc.update_stream(contents, doc.xref_stream(contents) +
                      b"\nBT /F1 12 Tf 100 700 Td (AB\\012  0\\012LINE\\012  8\\012X) Tj ET\n")
    data = doc.tobytes()
    doc.close()
    return data


def test_malicious_content_is_not_copied(make_client, tmp_path):
    client = make_client()
    job = upload(client, make_malicious_pdf(), format="dxf")
    assert job["status"] == "done", job
    content = client.get(f"/api/jobs/{job['id']}/download").content
    for marker in (b"EVILPAYLOAD", b"EVILJS", b"cmd.exe", b"JavaScript"):
        assert marker not in content
    saved = tmp_path / "wynik.dxf"
    saved.write_bytes(content)
    msp = ezdxf.readfile(saved).modelspace()
    assert len(msp.query("LINE")) == 1  # znaki nowej linii w tekście nie dodały obiektów
    assert all("\n" not in t.dxf.text for t in msp.query("TEXT"))


def test_unreadable_pdf_does_not_leak_paths(make_client, tmp_path):
    client = make_client()
    doc = pymupdf.open()
    doc.new_page().draw_line((0, 0), (99, 99))
    encrypted = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="tajne",
                            owner_pw="wlasciciel")
    broken = b"%PDF-1.7\n" + bytes(range(256)) * 200
    for pdf, expected in ((encrypted, "hasłem"), (broken, "uszkodzony")):
        job = upload(client, pdf, format="dxf")
        assert job["status"] == "error" and expected in job["error"], job
        assert "input.pdf" not in job["error"] and str(tmp_path.name) not in job["error"]


def test_per_client_limit(make_client):
    client = make_client(max_active_per_client=1, workers=1)
    pdf = make_pdf()
    first = client.post("/api/jobs", files={"file": ("a.pdf", pdf)}, data={"format": "dxf"})
    second = client.post("/api/jobs", files={"file": ("b.pdf", pdf)}, data={"format": "dxf"})
    assert first.status_code == 202
    assert second.status_code == 429
    wait(client, first.json()["id"])


def test_delete_job(make_client):
    client = make_client()
    job = upload(client, make_pdf(), format="dxf")
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 204
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404


def test_options_parsing():
    assert parse_scale("1:50") == parse_scale("50") == parse_scale("1/50") == 50
    assert parse_scale("") == 1
    assert parse_pages("1,3-5", 100) == [1, 3, 4, 5]
    assert parse_pages(" ", 100) is None
    with pytest.raises(OptionsError):
        parse_pages("1-999999999", 100)
    with pytest.raises(OptionsError):
        parse_pages("1-200", 100)
    with pytest.raises(OptionsError):
        parse_scale("abc")
    assert safe_stem("C:\\dok\\Stół #1.pdf") == "Stół #1"
    assert safe_stem("../../etc/passwd") == "passwd"
    assert safe_stem("CON.pdf") == "_CON"
    assert safe_stem("???.pdf") == "rysunek"
