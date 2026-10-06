"""Resume file intake (IN-3): PDF, DOCX or plain text to text."""

from __future__ import annotations

import io
import zipfile
from typing import Literal

import docx
from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_RESUME_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 20

DocumentKind = Literal["pdf", "docx", "text"]

KIND_EXTENSIONS: dict[DocumentKind, str] = {"pdf": "pdf", "docx": "docx", "text": "txt"}


class DocumentError(ValueError):
    pass


def detect_kind(data: bytes, filename: str | None = None) -> DocumentKind:
    """Detect the type from the bytes, not the name, so a renamed file cannot fool us."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if "word/document.xml" in zf.namelist():
                    return "docx"
        except zipfile.BadZipFile:
            pass
        raise DocumentError("The file is a ZIP archive but not a Word (.docx) document.")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        name = f" ({filename})" if filename else ""
        raise DocumentError(f"Unsupported file type{name}. Use PDF, DOCX or plain text.") from exc
    return "text"


def document_text(data: bytes, filename: str | None = None) -> tuple[DocumentKind, str]:
    if len(data) > MAX_RESUME_BYTES:
        raise DocumentError(f"The file is larger than {MAX_RESUME_BYTES // (1024 * 1024)} MB.")
    kind = detect_kind(data, filename)
    if kind == "pdf":
        text = _pdf_text(data)
    elif kind == "docx":
        text = _docx_text(data)
    else:
        text = data.decode("utf-8")
    text = text.strip()
    if not text:
        raise DocumentError(
            "No text found in the file. A scanned PDF has no text layer; paste the text instead."
        )
    return kind, text


def _pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentError("The PDF is password protected.")
        pages = reader.pages[:MAX_PDF_PAGES]
        return "\n\n".join(page.extract_text() or "" for page in pages)
    except PdfReadError as exc:
        raise DocumentError(f"The PDF could not be read: {exc}") from exc


def _docx_text(data: bytes) -> str:
    document = docx.Document(io.BytesIO(data))
    lines: list[str] = []
    for paragraph in document.paragraphs:
        lines.append(_visible_text(paragraph))
    for table in document.tables:
        for row in table.rows:
            cells = [" ".join(_visible_text(p) for p in cell.paragraphs) for cell in row.cells]
            lines.append(" | ".join(dict.fromkeys(c for c in cells if c)))
    return "\n".join(lines)


def _visible_text(paragraph: object) -> str:
    """Text of the runs a reader can see. Hidden runs are a common way to plant instructions."""
    runs = getattr(paragraph, "runs", [])
    return "".join(run.text for run in runs if not run.font.hidden)
