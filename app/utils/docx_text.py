"""Safe text extraction for uploaded .docx resumes (in memory only, nothing is written to disk)."""
import io
import math
import zipfile

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.core.errors import ValidationFailed
from app.utils.pdf import clean_text

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MAX_UNCOMPRESSED_BYTES = 30 * 1024 * 1024   # zip-bomb guard: a 5 MB upload may not expand beyond this
MAX_ZIP_MEMBERS = 2000
WORDS_PER_PAGE = 500                         # .docx has no fixed pages; this estimates the length for the page limit


def _table_lines(table: Table) -> list[str]:
    lines = []
    for row in table.rows:
        cells: list[str] = []
        for cell in row.cells:
            text = " ".join(p.text.strip() for p in cell.paragraphs if p.text.strip())
            if text and (not cells or cells[-1] != text):      # merged cells repeat their text
                cells.append(text)
        if cells:
            lines.append(" | ".join(cells))
    return lines


def extract_docx_text(data: bytes, *, max_pages: int) -> tuple[str, int]:
    """Return (text, estimated_page_count). Raises ValidationFailed for invalid, oversized or empty files."""
    if not data.startswith(b"PK\x03\x04"):
        raise ValidationFailed("File is not a valid .docx (bad file signature). Old .doc files are not supported; "
                               "save the resume as .docx or PDF.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_MEMBERS or sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_BYTES:
                raise ValidationFailed("This .docx file is unusually large when unpacked and was rejected.")
            if "word/document.xml" not in {i.filename for i in infos}:
                raise ValidationFailed("File is not a Word document (word/document.xml is missing).")
        doc = Document(io.BytesIO(data))
        lines: list[str] = []
        for block in doc.iter_inner_content():
            if isinstance(block, Paragraph):
                if block.text.strip():
                    lines.append(block.text.strip())
            elif isinstance(block, Table):
                lines.extend(_table_lines(block))
    except ValidationFailed:
        raise
    except (zipfile.BadZipFile, KeyError, ValueError, TypeError, OSError, AttributeError) as exc:
        raise ValidationFailed("Could not read the .docx file.") from exc
    except Exception as exc:  # noqa: BLE001 - python-docx raises PackageNotFoundError and lxml errors for corrupt files
        raise ValidationFailed("Could not read the .docx file.") from exc

    text = clean_text("\n".join(lines))
    if len(text) < 30:
        raise ValidationFailed("No readable text found in the .docx file.")
    pages = max(1, math.ceil(len(text.split()) / WORDS_PER_PAGE))
    if pages > max_pages:
        raise ValidationFailed(f"Resume is about {pages} pages long; the maximum is {max_pages}.")
    return text, pages
