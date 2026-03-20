"""
Ingestion service.

Converts raw input (PDF bytes, text bytes, or plain string) into a
normalised text string for downstream extraction.

Strategy:
  1. If the input looks like a PDF (magic bytes %PDF), parse with pdfplumber.
  2. If pdfplumber fails, fall back to decoding bytes as UTF-8 text.
  3. If the input is already a string, pass it through unchanged.
"""

from __future__ import annotations

import logging
from io import BytesIO

import pdfplumber

from app.core.exceptions import PDFParseError

logger = logging.getLogger(__name__)

_PDF_MAGIC = b"%PDF"


def ingest(content: bytes | str, filename: str = "") -> str:
    """
    Normalise raw invoice content to plain text.

    Args:
        content: Raw bytes (PDF or text) or a pre-decoded string.
        filename: Optional filename, used only for log context.

    Returns:
        Extracted text, stripped of leading/trailing whitespace.

    Raises:
        PDFParseError: If the content claims to be a PDF but cannot be parsed
                       and the fallback text decode also fails.
    """
    if isinstance(content, str):
        return content.strip()

    if _is_pdf(content):
        return _parse_pdf(content, filename)

    return _decode_text(content, filename)


# ── private helpers ───────────────────────────────────────────────────────────

def _is_pdf(data: bytes) -> bool:
    return data[:4] == _PDF_MAGIC


def _parse_pdf(data: bytes, filename: str) -> str:
    """Extract text from PDF bytes using pdfplumber, with text fallback."""
    try:
        with pdfplumber.open(BytesIO(data)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        text = "\n".join(pages).strip()
        logger.info("PDF ingested", extra={"source_file": filename, "pages": len(pages)})
        return text
    except Exception as e:
        logger.warning(
            "pdfplumber failed, attempting text fallback",
            extra={"source_file": filename, "error": str(e)},
        )
        try:
            return data.decode("utf-8", errors="replace").strip()
        except Exception as decode_err:
            raise PDFParseError(f"Failed to ingest PDF '{filename}'") from decode_err


def _decode_text(data: bytes, filename: str) -> str:
    """Decode raw bytes as UTF-8 text."""
    try:
        text = data.decode("utf-8", errors="replace").strip()
        logger.info("Text content ingested", extra={"source_file": filename, "bytes": len(data)})
        return text
    except Exception as e:
        raise PDFParseError(f"Failed to decode content from '{filename}'") from e
