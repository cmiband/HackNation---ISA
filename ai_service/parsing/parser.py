"""Uploaded request file (PDF / DOCX) → plain UTF-8 text.

Usage:
    parser = DocumentParser.from_env()             # create once and reuse (thread-safe)
    doc = parser.parse(filename, data)             # data: bytes (e.g. st.file_uploader(...).getvalue())
    doc.text, doc.method                           # method: "docx" | "pdf_text" | "pdf_ocr"
    parser.parse_path("request.pdf")               # convenience for scripts

PDFs with a text layer are read locally (pypdf). Scanned PDFs (no text layer) are transcribed by the LLM
(`ai_service.llm.ocr`); without an LLM they raise DocumentParseError.
"""

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import docx
import pypdf
from docx.table import Table

from ai_service.llm.ocr import LLMOcr

ParseMethod = Literal["docx", "pdf_text", "pdf_ocr"]

# Below this many extracted characters per page on average, a PDF is treated as scanned.
_MIN_CHARS_PER_PAGE = 30


class DocumentParseError(ValueError):
    """The file cannot be turned into text; the message is safe to show to the user."""


@dataclass(frozen=True)
class ParsedDocument:
    filename: str
    text: str
    method: ParseMethod
    pages: int | None = None


class DocumentParser:
    def __init__(self, ocr: LLMOcr | None) -> None:
        self._ocr = ocr

    @classmethod
    def from_env(cls) -> "DocumentParser":
        return cls(LLMOcr.from_env())

    def parse_path(self, path: str | Path) -> ParsedDocument:
        path = Path(path)
        return self.parse(path.name, path.read_bytes())

    def parse(self, filename: str, data: bytes) -> ParsedDocument:
        if not data:
            raise DocumentParseError(f"File '{filename}' is empty.")
        suffix = Path(filename).suffix.lower()
        if suffix == ".docx":
            doc = ParsedDocument(filename, _docx_text(filename, data), "docx")
        elif suffix == ".pdf":
            doc = self._parse_pdf(filename, data)
        elif suffix == ".doc":
            raise DocumentParseError(
                f"'{filename}': legacy .doc is not supported. Save it as .docx or PDF and upload again."
            )
        else:
            raise DocumentParseError(f"'{filename}': unsupported file type. Upload a PDF or .docx file.")

        if not doc.text.strip():
            raise DocumentParseError(f"No text found in '{filename}'.")
        return doc

    def _parse_pdf(self, filename: str, data: bytes) -> ParsedDocument:
        try:
            reader = pypdf.PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise DocumentParseError(f"'{filename}' is password-protected.")
            pages = len(reader.pages)
            text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
        except pypdf.errors.PyPdfError as exc:
            raise DocumentParseError(f"'{filename}' is not a valid PDF file.") from exc

        if len(text) >= _MIN_CHARS_PER_PAGE * max(pages, 1):
            return ParsedDocument(filename, _normalize(text), "pdf_text", pages)

        # Scanned PDF: no usable text layer.
        if self._ocr is None:
            raise DocumentParseError(
                f"'{filename}' is a scanned PDF without a text layer; OCR needs the LLM (set LLM_MODEL)."
            )
        return ParsedDocument(filename, _normalize(self._ocr.transcribe(data)), "pdf_ocr", pages)


def _docx_text(filename: str, data: bytes) -> str:
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # python-docx raises several unrelated types for broken files
        raise DocumentParseError(f"'{filename}' is not a valid .docx file.") from exc

    blocks: list[str] = []
    for block in document.iter_inner_content():  # paragraphs and tables in document order
        if isinstance(block, Table):
            for row in block.rows:
                cells = [cell.text.strip() for cell in row.cells]
                blocks.append(" | ".join(c for c in cells if c))
        else:
            blocks.append(block.text)
    return _normalize("\n".join(blocks))


def _normalize(text: str) -> str:
    """Trim trailing spaces and collapse runs of blank lines."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()
