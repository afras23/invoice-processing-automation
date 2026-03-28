"""
Unit tests for the document parser modules and factory.

Covers:
- Parser factory: returns correct parser, raises on unknown format
- PDF parser: page anchors, scanned detection, empty pages, corrupt files, content hash
- CSV parser: comma delimiter, tab delimiter (Sniffer), empty CSV
- Image parser: flags needs_ocr, raises on corrupt image bytes
- Parameterised format scenarios
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import PDFParseError
from app.models.invoice import ParsedDocument
from app.services.parsing import SUPPORTED_FORMATS, get_parser
from app.services.parsing.csv_parser import parse_csv
from app.services.parsing.image_parser import parse_image
from app.services.parsing.pdf_parser import _needs_ocr, parse_document

# ── Parser factory ────────────────────────────────────────────────────────────


def test_get_parser_pdf_returns_callable():
    parser = get_parser("pdf")
    assert callable(parser)


def test_get_parser_csv_returns_callable():
    parser = get_parser("csv")
    assert callable(parser)


def test_get_parser_image_returns_callable():
    parser = get_parser("image")
    assert callable(parser)


def test_get_parser_text_returns_callable():
    parser = get_parser("text")
    assert callable(parser)


def test_get_parser_case_insensitive():
    assert get_parser("PDF") is get_parser("pdf")


def test_get_parser_unknown_format_raises():
    with pytest.raises(PDFParseError, match="Unsupported file format"):
        get_parser("docx")


def test_supported_formats_constant():
    assert SUPPORTED_FORMATS == {"pdf", "csv", "image", "text"}


# ── PDF parser ────────────────────────────────────────────────────────────────


def test_pdf_string_input_returns_parsed_document():
    doc = parse_document("Invoice from Acme Corp")
    assert isinstance(doc, ParsedDocument)
    assert doc.text == "Invoice from Acme Corp"
    assert doc.format == "text"


def test_pdf_string_input_is_stripped():
    doc = parse_document("  Invoice  ")
    assert doc.text == "Invoice"


def test_pdf_plain_bytes_decoded_as_text():
    doc = parse_document(b"Invoice total: 500.00")
    assert doc.text == "Invoice total: 500.00"
    assert doc.format == "text"


def test_pdf_bytes_with_page_anchors():
    mock_page1 = MagicMock()
    mock_page1.extract_text.return_value = "Vendor: Acme Corp"
    mock_page2 = MagicMock()
    mock_page2.extract_text.return_value = "Total: 1500.00"
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page1, mock_page2]
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)

    with patch("app.services.parsing.pdf_parser.pdfplumber.open", return_value=mock_pdf):
        doc = parse_document(b"%PDF-1.4 fake", filename="invoice.pdf")

    assert "--- Page 1 ---" in doc.text
    assert "--- Page 2 ---" in doc.text
    assert "Vendor: Acme Corp" in doc.text
    assert "Total: 1500.00" in doc.text
    assert doc.format == "pdf"
    assert doc.page_count == 2


def test_pdf_empty_pages_are_skipped():
    mock_empty_page = MagicMock()
    mock_empty_page.extract_text.return_value = ""
    mock_text_page = MagicMock()
    mock_text_page.extract_text.return_value = "Invoice No: INV-001"
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_empty_page, mock_text_page]
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)

    with patch("app.services.parsing.pdf_parser.pdfplumber.open", return_value=mock_pdf):
        doc = parse_document(b"%PDF-1.4 fake", filename="mixed.pdf")

    assert "--- Page 1 ---" not in doc.text
    assert "--- Page 2 ---" in doc.text
    assert doc.page_count == 2


def test_pdf_scanned_detection_sets_needs_ocr():
    # All pages have no text → scanned PDF
    mock_page = MagicMock()
    mock_page.extract_text.return_value = ""
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page, mock_page, mock_page]
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)

    with patch("app.services.parsing.pdf_parser.pdfplumber.open", return_value=mock_pdf):
        doc = parse_document(b"%PDF-1.4 fake", filename="scanned.pdf")

    assert doc.needs_ocr is True


def test_pdf_parse_failure_falls_back_to_text_decode():
    with patch(
        "app.services.parsing.pdf_parser.pdfplumber.open",
        side_effect=Exception("corrupt pdf"),
    ):
        doc = parse_document(b"%PDFsome plain text", filename="bad.pdf")

    assert "some plain text" in doc.text
    assert doc.format == "pdf"


def test_pdf_content_hash_is_stable():
    doc1 = parse_document("Invoice: Acme Corp, total 1000")
    doc2 = parse_document("Invoice: Acme Corp, total 1000")
    assert doc1.content_hash == doc2.content_hash


def test_pdf_different_text_has_different_hash():
    doc1 = parse_document("Invoice A")
    doc2 = parse_document("Invoice B")
    assert doc1.content_hash != doc2.content_hash


def test_needs_ocr_true_when_all_pages_empty():
    assert _needs_ocr(["", "   ", "\n"]) is True


def test_needs_ocr_false_when_pages_have_text():
    assert _needs_ocr(["Invoice text", "More text"]) is False


def test_needs_ocr_false_for_empty_list():
    assert _needs_ocr([]) is False


# ── CSV parser ────────────────────────────────────────────────────────────────


def test_csv_comma_delimited_parsed():
    csv_bytes = b"vendor,amount\nAcme Corp,1500.00"
    doc = parse_csv(csv_bytes, filename="invoice.csv")
    assert "vendor: Acme Corp" in doc.text
    assert "amount: 1500.00" in doc.text
    assert doc.format == "csv"


def test_csv_tab_delimited_detected_by_sniffer():
    csv_bytes = b"vendor\tamount\nAcme Corp\t1500.00"
    doc = parse_csv(csv_bytes, filename="invoice.csv")
    assert "vendor: Acme Corp" in doc.text
    assert "amount: 1500.00" in doc.text


def test_csv_empty_file_returns_empty_text():
    doc = parse_csv(b"", filename="empty.csv")
    assert doc.text == ""
    assert doc.format == "csv"


def test_csv_string_input_accepted():
    doc = parse_csv("vendor,amount\nTest Corp,200.00")
    assert "vendor: Test Corp" in doc.text


def test_csv_content_hash_computed():
    doc = parse_csv(b"vendor,amount\nAcme,100")
    assert len(doc.content_hash) == 64  # SHA-256 hex


def test_csv_row_anchors_present():
    csv_bytes = b"vendor,amount\nAcme,100\nBeta,200"
    doc = parse_csv(csv_bytes)
    assert "--- Row 1 ---" in doc.text
    assert "--- Row 2 ---" in doc.text


# ── Image parser ──────────────────────────────────────────────────────────────


def test_image_parser_sets_needs_ocr():
    mock_image = MagicMock()
    mock_image.format = "JPEG"
    mock_image.size = (800, 600)

    with patch("PIL.Image.open", return_value=mock_image):
        doc = parse_image(b"\xff\xd8fake_jpeg", filename="invoice.jpg")

    assert doc.needs_ocr is True
    assert doc.format == "image"


def test_image_parser_corrupt_bytes_raises():
    with patch("PIL.Image.open", side_effect=Exception("not an image")):
        with pytest.raises(PDFParseError, match="Failed to open image"):
            parse_image(b"not_an_image", filename="bad.png")


# ── Parameterised scenarios ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "content,expected_format",
    [
        ("plain text invoice", "text"),
        (b"plain bytes invoice", "text"),
        (b"%PDF-fake content", "pdf"),
    ],
)
def test_parse_document_format_detection(content: bytes | str, expected_format: str):
    if expected_format == "pdf":
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "content"
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = lambda s: s
        mock_pdf.__exit__ = MagicMock(return_value=False)
        with patch("app.services.parsing.pdf_parser.pdfplumber.open", return_value=mock_pdf):
            doc = parse_document(content)
    else:
        doc = parse_document(content)
    assert doc.format == expected_format
