import io

import docx
import pypdf
import pytest
from pydantic_ai import models
from pydantic_ai.models.test import TestModel

from ai_service.llm.ocr import LLMOcr
from ai_service.parsing import DocumentParseError, DocumentParser

models.ALLOW_MODEL_REQUESTS = False


def _docx_bytes() -> bytes:
    document = docx.Document()
    document.add_paragraph("Dzień dobry,")
    document.add_paragraph("proszę o informację o budżecie obywatelskim – zażółć gęślą jaźń.")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Ulica"
    table.rows[0].cells[1].text = "Gdańska"
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _text_pdf_bytes(text: str) -> bytes:
    """Minimal one-page PDF with a real text layer (Helvetica, ASCII text)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref))
    return out.getvalue()


def _blank_pdf_bytes() -> bytes:
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_docx_paragraphs_and_tables_with_polish_characters():
    doc = DocumentParser(None).parse("wniosek.docx", _docx_bytes())
    assert doc.method == "docx"
    assert "zażółć gęślą jaźń" in doc.text
    assert "Ulica | Gdańska" in doc.text


def test_pdf_with_text_layer_is_read_locally():
    text = "Prosze o informacje dotyczace liczby uczniow w szkolach podstawowych w Bydgoszczy."
    doc = DocumentParser(None).parse("wniosek.pdf", _text_pdf_bytes(text))
    assert doc.method == "pdf_text"
    assert "liczby uczniow" in doc.text
    assert doc.pages == 1


def test_scanned_pdf_goes_to_ocr():
    ocr = LLMOcr(TestModel(custom_output_text="Wniosek o udostępnienie informacji publicznej"))
    doc = DocumentParser(ocr).parse("skan.pdf", _blank_pdf_bytes())
    assert doc.method == "pdf_ocr"
    assert doc.text == "Wniosek o udostępnienie informacji publicznej"


def test_scanned_pdf_without_llm_raises():
    with pytest.raises(DocumentParseError, match="scanned"):
        DocumentParser(None).parse("skan.pdf", _blank_pdf_bytes())


@pytest.mark.parametrize(
    ("filename", "data", "match"),
    [
        ("pusty.pdf", b"", "empty"),
        ("stary.doc", b"x", "legacy"),
        ("obraz.png", b"x", "unsupported"),
        ("zly.pdf", b"not a pdf", "not a valid PDF"),
        ("zly.docx", b"not a docx", "not a valid .docx"),
    ],
)
def test_invalid_files_raise_clear_errors(filename, data, match):
    with pytest.raises(DocumentParseError, match=match):
        DocumentParser(None).parse(filename, data)
