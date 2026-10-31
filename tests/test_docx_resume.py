"""DOCX resumes alongside PDF."""
import io
import zipfile

from docx import Document

from app.utils.docx_text import DOCX_MIME
from tests.sample_data import RESUME_TEXT

HEADINGS = {"Summary", "Experience", "Education", "Projects", "Skills", "Certifications"}


def make_docx(text: str = RESUME_TEXT, *, table_skills: str | None = None) -> bytes:
    doc = Document()
    for line in text.splitlines():
        p = doc.add_paragraph(line)
        if line.strip() in HEADINGS:
            p.style = "Heading 1"
    if table_skills:                                   # many real resumes lay sections out in tables
        t = doc.add_table(rows=1, cols=2)
        t.rows[0].cells[0].text = "Tools"
        t.rows[0].cells[1].text = table_skills
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


async def upload(client, auth, data, name="resume.docx", ctype=DOCX_MIME):
    return await client.post("/api/profile/resume", headers=auth, files={"file": (name, data, ctype)})


async def test_docx_resume_is_parsed_like_a_pdf(client, auth):
    r = await upload(client, auth, make_docx())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["filename"] == "resume.docx" and body["parse_status"] == "parsed" and body["page_count"] >= 1
    names = {s["name"] for s in body["parsed_data"]["technical_skills"]}
    assert {"SQL", "Python", "Pandas", "Tableau"} <= names
    assert body["parsed_data"]["years_experience"] == 4
    assert (await client.get("/api/profile", headers=auth)).json()["needs_review"] is True


async def test_text_inside_tables_is_read(client, auth):
    r = await upload(client, auth, make_docx("Jo Doe\nData Analyst\nSkills\nCommunication", table_skills="Kubernetes, Terraform, Docker"))
    assert r.status_code == 201, r.text
    names = {s["name"] for s in r.json()["parsed_data"]["technical_skills"]}
    assert {"Kubernetes", "Terraform", "Docker"} <= names


async def test_pdf_still_works_and_octet_stream_is_accepted_for_docx(client, auth):
    from tests.conftest import make_pdf

    assert (await upload(client, auth, make_pdf(RESUME_TEXT), name="r.pdf", ctype="application/pdf")).status_code == 201
    assert (await upload(client, auth, make_docx(), ctype="application/octet-stream")).status_code == 201


async def test_bad_docx_files_are_rejected_cleanly(client, auth):
    cases = {
        "not a zip": (b"this is plain text pretending to be a docx " * 4, "resume.docx"),
        "zip without word/document.xml": (_zip({"hello.txt": b"hi"}), "resume.docx"),
        "legacy .doc": (b"\xd0\xcf\x11\xe0" + b"0" * 200, "resume.doc"),
        "empty document": (make_docx("hi"), "resume.docx"),
        "mismatched mime": (make_docx(), "resume.docx"),
    }
    for label, (data, name) in cases.items():
        ctype = "application/pdf" if label == "mismatched mime" else DOCX_MIME
        r = await upload(client, auth, data, name=name, ctype=ctype)
        assert r.status_code == 422, (label, r.status_code, r.text)
        assert "error" in r.json()


async def test_zip_bomb_is_rejected_without_unpacking(client, auth):
    bomb = _zip({"word/document.xml": b"<w:document/>", "word/big.bin": b"\0" * (35 * 1024 * 1024)})
    assert len(bomb) < 5 * 1024 * 1024                         # small upload, huge once unpacked
    r = await upload(client, auth, bomb)
    assert r.status_code == 422 and "unusually large" in r.json()["error"]["message"]


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()
