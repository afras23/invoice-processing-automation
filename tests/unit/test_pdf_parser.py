"""
Unit tests for the PDF / document parsing service.

These tests confirm that parse_document returns a ParsedDocument with
correct text, format, and content_hash fields.
"""

from unittest.mock import MagicMock, patch

from app.models.invoice import ParsedDocument
from app.services.parsing.pdf_parser import parse_document


def test_string_input_returns_parsed_document_with_stripped_text():
    doc = parse_document("  Invoice from Acme Corp  ")
    assert isinstance(doc, ParsedDocument)
    assert doc.text == "Invoice from Acme Corp"
    assert doc.format == "text"


def test_plain_text_bytes_are_decoded():
    doc = parse_document(b"Invoice total: 500.00")
    assert doc.text == "Invoice total: 500.00"
    assert doc.format == "text"


def test_pdf_bytes_are_parsed_via_pdfplumber():
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Vendor: Acme Corp"
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)

    with patch("app.services.parsing.pdf_parser.pdfplumber.open", return_value=mock_pdf):
        doc = parse_document(b"%PDF-1.4 fake", filename="invoice.pdf")

    assert "Vendor: Acme Corp" in doc.text
    assert doc.format == "pdf"


def test_pdf_parse_failure_falls_back_to_text_decode():
    with patch(
        "app.services.parsing.pdf_parser.pdfplumber.open",
        side_effect=Exception("bad pdf"),
    ):
        doc = parse_document(b"%PDFsome plain text", filename="bad.pdf")

    assert "some plain text" in doc.text


def test_empty_string_returns_empty_text():
    doc = parse_document("")
    assert doc.text == ""


def test_whitespace_only_string_is_stripped():
    doc = parse_document("   \n\t  ")
    assert doc.text == ""


def test_content_hash_is_64_hex_chars():
    doc = parse_document("some invoice text")
    assert len(doc.content_hash) == 64
    assert all(c in "0123456789abcdef" for c in doc.content_hash)
