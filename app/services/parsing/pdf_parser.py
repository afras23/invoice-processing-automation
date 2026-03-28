"""
PDF and raw-bytes document parser.

Converts raw input (PDF bytes, plain-text bytes, or a pre-decoded string)
into a ParsedDocument with normalised text and a content hash.

Strategy:
  1. String input  → wrap as plain text ParsedDocument.
  2. PDF bytes (%PDF magic) → parse with pdfplumber, page by page.
  3. pdfplumber failure → fall back to UTF-8 decode.
  4. Non-PDF bytes → decode as UTF-8.

Scanned PDF detection: if ≥50% of pages yield no extractable text,
needs_ocr is set to True in the returned ParsedDocument.
"""

from __future__ import annotations

import hashlib
import logging
from io import BytesIO

import pdfplumber

from app.core.exceptions import PDFParseError
from app.models.invoice import ParsedDocument

logger = logging.getLogger(__name__)

_PDF_MAGIC = b"%PDF"
_PAGE_ANCHOR = "--- Page {page_num} ---"
_SCANNED_THRESHOLD = 0.5  # fraction of empty pages that triggers needs_ocr


def parse_document(content: bytes | str, filename: str = "") -> ParsedDocument:
    """
    Normalise raw invoice content to a ParsedDocument.

    Args:
        content: Raw bytes (PDF or text) or a pre-decoded string.
        filename: Optional filename used only for log context.

    Returns:
        ParsedDocument with extracted text, content hash, format, and
        scanned-PDF flag.

    Raises:
        PDFParseError: If the content is a PDF that cannot be parsed and the
            UTF-8 fallback also fails.
    """
    if isinstance(content, str):
        stripped = content.strip()
        return ParsedDocument(
            text=stripped,
            content_hash=_hash(stripped),
            format="text",
            filename=filename,
        )

    if _is_pdf(content):
        return _parse_pdf_bytes(content, filename)

    return _decode_text_bytes(content, filename)


# ── private helpers ───────────────────────────────────────────────────────────


def _is_pdf(data: bytes) -> bool:
    return data[:4] == _PDF_MAGIC


def _hash(text: str) -> str:
    normalised = " ".join(text.split())
    return hashlib.sha256(normalised.encode()).hexdigest()


def _parse_pdf_bytes(data: bytes, filename: str) -> ParsedDocument:
    """
    Extract text from PDF bytes using pdfplumber, page by page.

    Each non-empty page is prefixed with an anchor line so the AI model
    can reference specific pages.  Empty pages are skipped but counted.

    Args:
        data: Raw PDF bytes.
        filename: Source filename for log context.

    Returns:
        ParsedDocument with joined page text and scanned-PDF flag.

    Raises:
        PDFParseError: If pdfplumber fails and the fallback decode also fails.
    """
    try:
        with pdfplumber.open(BytesIO(data)) as pdf:
            raw_pages = [page.extract_text() or "" for page in pdf.pages]
            page_count = len(raw_pages)

        is_scanned = _needs_ocr(raw_pages)
        page_sections: list[str] = []
        for page_num, page_text in enumerate(raw_pages, start=1):
            if page_text.strip():
                page_sections.append(_PAGE_ANCHOR.format(page_num=page_num))
                page_sections.append(page_text.strip())

        extracted_text = "\n".join(page_sections)
        logger.info(
            "PDF parsed via pdfplumber",
            extra={
                "source_file": filename,
                "pages": page_count,
                "needs_ocr": is_scanned,
            },
        )
        return ParsedDocument(
            text=extracted_text,
            content_hash=_hash(extracted_text),
            format="pdf",
            page_count=page_count,
            needs_ocr=is_scanned,
            filename=filename,
        )
    except PDFParseError:
        raise
    except Exception as pdf_exc:
        logger.warning(
            "pdfplumber failed, attempting UTF-8 fallback",
            extra={"source_file": filename, "error": str(pdf_exc)},
        )
        try:
            fallback_text = data.decode("utf-8", errors="replace").strip()
            return ParsedDocument(
                text=fallback_text,
                content_hash=_hash(fallback_text),
                format="pdf",
                filename=filename,
            )
        except Exception as decode_exc:
            raise PDFParseError(
                f"Failed to parse PDF '{filename}'",
                context={"source_file": filename},
            ) from decode_exc


def _decode_text_bytes(data: bytes, filename: str) -> ParsedDocument:
    """
    Decode raw bytes as UTF-8 text.

    Args:
        data: Raw bytes that are not a PDF.
        filename: Source filename for log context.

    Returns:
        ParsedDocument wrapping the decoded text.

    Raises:
        PDFParseError: If the bytes cannot be decoded.
    """
    try:
        decoded_text = data.decode("utf-8", errors="replace").strip()
        logger.info(
            "Text content parsed",
            extra={"source_file": filename, "bytes": len(data)},
        )
        return ParsedDocument(
            text=decoded_text,
            content_hash=_hash(decoded_text),
            format="text",
            filename=filename,
        )
    except Exception as exc:
        raise PDFParseError(
            f"Failed to decode content from '{filename}'",
            context={"source_file": filename},
        ) from exc


def _needs_ocr(pages_text: list[str]) -> bool:
    """
    Return True if the PDF appears to be scanned (no extractable text).

    Args:
        pages_text: List of per-page text strings from pdfplumber.

    Returns:
        True if ≥50% of pages have no extractable text.
    """
    if not pages_text:
        return False
    empty_count = sum(1 for page_text in pages_text if not page_text.strip())
    return empty_count / len(pages_text) >= _SCANNED_THRESHOLD


# ── backward-compatibility alias ─────────────────────────────────────────────
# Callers that imported ingest from app.services.parsing.pdf_parser still work.
ingest = parse_document
