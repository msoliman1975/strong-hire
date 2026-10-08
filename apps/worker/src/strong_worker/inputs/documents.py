"""Resume file intake (IN-3): PDF, DOCX or plain text to text.

The text keeps the visual reading order, because the extractor files each achievement under
the role heading above it.

PDF: pypdf "layout" mode places every text piece on a character grid by its position on the
page, so the result follows what a reader sees, not the order the file draws the text in.
Default mode follows the drawing order: on a CV with a date column the next role's heading
came before the sub-sections of the role above it, and the extractor filed them under the
wrong role. Two more steps tidy the grid:

- A sidebar next to the main column (contact, skills, education) shares grid lines with the
  main column. When a page has a steady vertical gap with text on both sides, and the narrow
  side is not just dates, each side is read on its own: the left side first, then the right.
  A left date column or right-aligned dates stay on the line of their role heading.
- Runs of 2 or more spaces or tabs become two spaces, and repeated blank lines become one.

DOCX: paragraphs and tables are read in document order (a table is no longer moved to the
end), with the text of text boxes after the paragraph that anchors them. Hidden text is
dropped, because hidden runs are a common way to plant instructions for a model.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from collections.abc import Iterator
from typing import Any, Literal

import docx
from pypdf import PdfReader
from pypdf.errors import PdfReadError

log = logging.getLogger(__name__)

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


# --- PDF ------------------------------------------------------------------------------------


def _pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentError("The PDF is password protected.")
        pages = reader.pages[:MAX_PDF_PAGES]
        return "\n\n".join(_page_text(page) for page in pages)
    except PdfReadError as exc:
        raise DocumentError(f"The PDF could not be read: {exc}") from exc


def _page_text(page: Any) -> str:
    """The page in visual order. Falls back to drawing order if layout mode fails."""
    try:
        grid = page.extract_text(extraction_mode="layout") or ""
    except Exception as exc:  # layout mode needs font widths; some files lack them
        log.info("PDF layout mode failed (%s); using plain mode", type(exc).__name__)
        grid = ""
    if not grid.strip():
        return tidy_lines((page.extract_text() or "").splitlines())
    return layout_text(grid)


_SPACES = re.compile(r"[ \t]{2,}")
_MIN_SIDE_LINES = 4
_MIN_BOTH_SHARE = 0.2  # share of lines with text on both sides of a column edge
_MAX_CROSSING = 0.25  # share of lines that may run across the edge (a header, a footer)


def layout_text(grid: str) -> str:
    """Tidy pypdf layout output; read a sidebar and the main column one after the other."""
    lines = [line.rstrip() for line in grid.splitlines()]
    edge = _column_edge(lines)
    if edge is None:
        return tidy_lines(lines)
    out: list[str] = []
    left: list[str] = []
    right: list[str] = []

    def flush() -> None:
        out.extend(left)
        out.extend(right)
        left.clear()
        right.clear()

    for line in lines:
        if _crosses(line, edge):
            flush()
            out.append(line)
            continue
        head, tail = line[:edge], line[edge:]
        if head.strip():
            left.append(head)
        if tail.strip():
            right.append(tail)
    flush()
    return tidy_lines(out)


def tidy_lines(lines: list[str]) -> str:
    out: list[str] = []
    for line in lines:
        clean = _SPACES.sub("  ", line).strip()
        if clean or (out and out[-1]):
            out.append(clean)
    return "\n".join(out).strip()


def _crosses(line: str, edge: int) -> bool:
    """True when the line has text on both sides of the edge without a gap of 2 blank cells
    just before it: a word or a sentence runs over the edge."""
    if edge >= len(line) or not line[:edge].strip() or not line[edge:].strip():
        return False
    return line[edge - 2 : edge] != "  "


def _column_edge(lines: list[str]) -> int | None:
    """The grid column where a main column starts next to a sidebar, or None.

    The main column's lines all start at one grid column. A candidate edge is a column where
    many lines have sidebar text, a gap of at least 2 blank cells, and a word starting right
    at the edge; few lines may run across it. It is rejected when the text on one side is
    mostly dates, so a date column (or right-aligned dates) stays on the line of its role.
    """
    text_lines = [line for line in lines if line.strip()]
    n = len(text_lines)
    if n < 2 * _MIN_SIDE_LINES:
        return None
    need = max(_MIN_SIDE_LINES, _MIN_BOTH_SHARE * n)
    width = max(len(line) for line in text_lines)
    best: tuple[int, int] | None = None  # (lines with text on both sides, column)
    for col in range(8, width - 8):
        both = crossing = 0
        for line in text_lines:
            if _crosses(line, col):
                crossing += 1
            elif col < len(line) and line[col] != " " and line[:col].strip():
                both += 1
        if crossing > _MAX_CROSSING * n or both < need:
            continue
        if best is None or both > best[0]:
            best = (both, col)
    if best is None:
        return None
    col = best[1]
    sides = [line for line in text_lines if not _crosses(line, col)]
    left = [line[:col].strip() for line in sides if line[:col].strip()]
    right = [line[col:].strip() for line in sides if line[col:].strip()]
    if min(len(left), len(right)) < _MIN_SIDE_LINES:
        return None
    if _mostly_dates(left) or _mostly_dates(right):
        return None
    return col


_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE_WORDS = re.compile(rf"{_MONTH}|present|current|now|today|to|since|\d+", re.IGNORECASE)
_YEAR = re.compile(r"(?:19|20)\d\d")
_DATE_PUNCT = re.compile("[\\s\\-/.,|()\N{EN DASH}\N{EM DASH}]")


def _mostly_dates(fragments: list[str], share: float = 0.6) -> bool:
    """True when most fragments are dates or date ranges like "Sep 2025 - Present"."""

    def is_date(text: str) -> bool:
        rest = _DATE_WORDS.sub("", text)
        return bool(_YEAR.search(text)) and not _DATE_PUNCT.sub("", rest)

    return sum(is_date(f) for f in fragments) >= share * len(fragments)


# --- DOCX -----------------------------------------------------------------------------------

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
# Containers whose runs are part of the paragraph text.
_RUN_PARENTS = {
    f"{_W}hyperlink",
    f"{_W}ins",
    f"{_W}smartTag",
    f"{_W}sdtContent",
    f"{_W}sdt",
    f"{_W}fldSimple",
    f"{_W}customXml",
}


def _docx_text(data: bytes) -> str:
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # a damaged package or a file that only looks like DOCX
        raise DocumentError(f"The Word file could not be read: {exc}") from exc
    return "\n".join(_block_lines(document.element.body))


def _block_lines(container: Any) -> Iterator[str]:
    """Lines of the paragraphs and tables in `container`, in document order."""
    for child in container.iterchildren():
        if child.tag == f"{_W}p":
            yield _paragraph_text(child)
            for box in _text_boxes(child):
                yield from _block_lines(box)
        elif child.tag == f"{_W}tbl":
            yield from _table_lines(child)
        elif child.tag == f"{_W}sdt":
            content = child.find(f"{_W}sdtContent")
            if content is not None:
                yield from _block_lines(content)


def _table_lines(table: Any) -> Iterator[str]:
    """A row of one-line cells becomes "a | b"; a row with longer cells is read cell by cell."""
    for row in table.iterchildren(f"{_W}tr"):
        cells = [list(_block_lines(cell)) for cell in row.iterchildren(f"{_W}tc")]
        cells = [[line for line in cell if line.strip()] for cell in cells]
        cells = [cell for cell in cells if cell]
        if all(len(cell) == 1 for cell in cells):
            if cells:
                yield " | ".join(dict.fromkeys(cell[0] for cell in cells))
        else:
            for cell in cells:
                yield from cell


def _paragraph_text(paragraph: Any) -> str:
    parts: list[str] = []
    for run in _runs(paragraph):
        if _hidden(run):
            continue
        for item in run.iterchildren():
            if item.tag == f"{_W}t":
                parts.append(item.text or "")
            elif item.tag == f"{_W}tab":
                parts.append("\t")
            elif item.tag in (f"{_W}br", f"{_W}cr"):
                parts.append("\n")
    return "".join(parts)


def _runs(paragraph: Any) -> Iterator[Any]:
    for child in paragraph.iterchildren():
        if child.tag == f"{_W}r":
            yield child
        elif child.tag in _RUN_PARENTS:
            yield from _runs(child)


def _hidden(run: Any) -> bool:
    props = run.find(f"{_W}rPr")
    if props is None:
        return False
    vanish = props.find(f"{_W}vanish")
    if vanish is None:
        return False
    return vanish.get(f"{_W}val", "true").lower() not in {"0", "false", "off"}


def _text_boxes(paragraph: Any) -> Iterator[Any]:
    """Text box contents anchored in the paragraph. A shape saved twice (DrawingML with a VML
    fallback) is read once: the fallback copy is skipped."""
    for box in paragraph.iter(f"{_W}txbxContent"):
        skip = False
        for above in box.iterancestors():
            if above is paragraph:
                break
            # A fallback copy, or a box inside another box (read with its outer box).
            if above.tag in (_MC_FALLBACK, f"{_W}txbxContent"):
                skip = True
                break
        if not skip:
            yield box
