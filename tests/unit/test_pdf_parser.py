"""
Unit tests for the PDF / document parsing service.
"""

from unittest.mock import MagicMock, patch

from app.services.parsing.pdf_parser import parse_document


def test_string_input_is_returned_stripped():
    assert parse_document("  Invoice from Acme Corp  ") == "Invoice from Acme Corp"


def test_plain_text_bytes_are_decoded():
    assert parse_document(b"Invoice total: 500.00") == "Invoice total: 500.00"


def test_pdf_bytes_are_parsed_via_pdfplumber():
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Vendor: Acme Corp"
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)

    with patch("app.services.parsing.pdf_parser.pdfplumber.open", return_value=mock_pdf):
        result = parse_document(b"%PDF-1.4 fake", filename="invoice.pdf")

    assert result == "Vendor: Acme Corp"


def test_pdf_parse_failure_falls_back_to_text_decode():
    with patch(
        "app.services.parsing.pdf_parser.pdfplumber.open",
        side_effect=Exception("bad pdf"),
    ):
        result = parse_document(b"%PDFsome plain text", filename="bad.pdf")

    assert "some plain text" in result


def test_empty_string_returns_empty_string():
    assert parse_document("") == ""


def test_whitespace_only_string_is_stripped():
    assert parse_document("   \n\t  ") == ""
