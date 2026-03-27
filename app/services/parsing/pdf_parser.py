"""
PDF and raw-bytes ingestion service.

Converts raw input (PDF bytes, plain-text bytes, or a pre-decoded string)
into a normalised text string for downstream AI extraction.

Strategy:
  1. String input  → strip and return unchanged.
  2. PDF bytes (%PDF magic) → parse with pdfplumber.
  3. pdfplumber failure → fall back to UTF-8 decode.
  4. Non-PDF bytes → decode as UTF-8.
"""

from __future__ import annotations

import logging
from io import BytesIO

import pdfplumber

from app.core.exceptions import PDFParseError

logger = logging.getLogger(__name__)

_PDF_MAGIC = b"%PDF"


def parse_document(content: bytes | str, filename: str = "") -> str:
    """
    Normalise raw invoice content to plain text.

    Args:
        content: Raw bytes (PDF or text) or a pre-decoded string.
        filename: Optional filename used only for log context.

    Returns:
        Extracted text, stripped of leading/trailing whitespace.

    Raises:
        PDFParseError: If the content is identified as a PDF but cannot be
            parsed and the fallback UTF-8 decode also fails.
    """
    if isinstance(content, str):
        return content.strip()

    if _is_pdf(content):
        return _parse_pdf_bytes(content, filename)

    return _decode_text_bytes(content, filename)


# ── private helpers ───────────────────────────────────────────────────────────


def _is_pdf(data: bytes) -> bool:
    return data[:4] == _PDF_MAGIC


def _parse_pdf_bytes(data: bytes, filename: str) -> str:
    """
    Extract text from PDF bytes using pdfplumber, with a UTF-8 fallback.

    Args:
        data: Raw PDF bytes.
        filename: Source filename for log context.

    Returns:
        Joined page text stripped of leading/trailing whitespace.

    Raises:
        PDFParseError: If pdfplumber fails and the fallback decode also fails.
    """
    try:
        with pdfplumber.open(BytesIO(data)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        extracted_text = "\n".join(pages).strip()
        logger.info(
            "PDF ingested via pdfplumber",
            extra={"source_file": filename, "pages": len(pages)},
        )
        return extracted_text
    except Exception as pdf_exc:
        logger.warning(
            "pdfplumber failed, attempting UTF-8 fallback",
            extra={"source_file": filename, "error": str(pdf_exc)},
        )
        try:
            return data.decode("utf-8", errors="replace").strip()
        except Exception as decode_exc:
            raise PDFParseError(
                f"Failed to ingest PDF '{filename}'",
                context={"source_file": filename},
            ) from decode_exc


def _decode_text_bytes(data: bytes, filename: str) -> str:
    """
    Decode raw bytes as UTF-8 text.

    Args:
        data: Raw bytes that are not a PDF.
        filename: Source filename for log context.

    Returns:
        Decoded and stripped text.

    Raises:
        PDFParseError: If the bytes cannot be decoded.
    """
    try:
        decoded_text = data.decode("utf-8", errors="replace").strip()
        logger.info(
            "Text content ingested",
            extra={"source_file": filename, "bytes": len(data)},
        )
        return decoded_text
    except Exception as exc:
        raise PDFParseError(
            f"Failed to decode content from '{filename}'",
            context={"source_file": filename},
        ) from exc


# ── backward-compatibility alias ─────────────────────────────────────────────
# app.services.ingestion.ingest is preserved here so existing callers keep working.
ingest = parse_document
