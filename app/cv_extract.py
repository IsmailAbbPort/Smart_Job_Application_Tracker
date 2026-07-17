"""Turn an uploaded CV file into plain text for embedding.

Two accepted formats: PDF (parsed with pypdf) and plain text. We sniff the
bytes rather than trusting the filename, so a mislabeled upload still routes
correctly. Anything we cannot decode comes back as an empty string, and the
caller (POST /cv/upload) rejects it with a 422.
"""

from __future__ import annotations

from io import BytesIO

_PDF_MAGIC = b"%PDF-"


def looks_like_pdf(filename: str, data: bytes) -> bool:
    """True if the bytes start with the PDF magic number, or the name says .pdf."""
    return data[:5] == _PDF_MAGIC or filename.lower().endswith(".pdf")


def extract_cv_text(filename: str, data: bytes) -> str:
    """Extract readable text from an uploaded CV (PDF or plain text)."""
    if looks_like_pdf(filename, data):
        return _extract_pdf_text(data)
    return data.decode("utf-8", errors="replace").strip()


def _extract_pdf_text(data: bytes) -> str:
    # Imported lazily so the dependency is only touched when a PDF is uploaded.
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages).strip()
