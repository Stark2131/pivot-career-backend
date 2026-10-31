"""Safe PDF text extraction for uploaded resumes."""
import io
import re

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.errors import ValidationFailed


def extract_pdf_text(data: bytes, *, max_pages: int) -> tuple[str, int]:
    """Return (text, page_count). Raises ValidationFailed for invalid/encrypted/empty PDFs.

    The file is processed in memory only; nothing is written to disk.
    """
    if not data.startswith(b"%PDF-"):
        raise ValidationFailed("File is not a valid PDF (bad file signature).")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValidationFailed("Encrypted/password-protected PDFs are not supported.")
        page_count = len(reader.pages)
        if page_count > max_pages:
            raise ValidationFailed(f"Resume has {page_count} pages; the maximum is {max_pages}.")
        parts = [(page.extract_text() or "") for page in reader.pages]
    except ValidationFailed:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        raise ValidationFailed("Could not read the PDF file.") from exc

    text = clean_text("\n".join(parts))
    if len(text) < 30:
        raise ValidationFailed(
            "No readable text found in the PDF. Scanned/image-only resumes are not supported yet; "
            "please upload a text-based PDF."
        )
    return text, page_count


def clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
