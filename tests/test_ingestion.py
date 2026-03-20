"""
Tests for the ingestion service.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.services.ingestion import ingest


def test_string_input_is_returned_unchanged():
    text = "  Invoice from Acme Corp  "
    assert ingest(text) == "Invoice from Acme Corp"


def test_plain_text_bytes_are_decoded():
    content = b"Invoice total: 500.00"
    assert ingest(content) == "Invoice total: 500.00"


def test_pdf_bytes_are_parsed_via_pdfplumber():
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Vendor: Acme Corp"
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)

    with patch("app.services.ingestion.pdfplumber.open", return_value=mock_pdf):
        result = ingest(b"%PDF-1.4 fake", filename="invoice.pdf")

    assert result == "Vendor: Acme Corp"


def test_pdf_parse_failure_falls_back_to_text_decode():
    """If pdfplumber raises, the raw bytes should be decoded as UTF-8."""
    with patch("app.services.ingestion.pdfplumber.open", side_effect=Exception("bad pdf")):
        result = ingest(b"%PDFsome plain text", filename="bad.pdf")

    assert "some plain text" in result


def test_empty_string_returns_empty_string():
    assert ingest("") == ""


def test_whitespace_only_string_is_stripped():
    assert ingest("   \n\t  ") == ""
