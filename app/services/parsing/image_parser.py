"""
Image invoice parser.

Extracts text from image-based invoices (JPEG, PNG, TIFF) using OCR.
Currently a stub — Pillow is available in requirements; wire up
pytesseract or a cloud vision API to activate.
"""

from __future__ import annotations

import logging

from app.core.exceptions import PDFParseError

logger = logging.getLogger(__name__)


def parse_image(data: bytes, filename: str = "") -> str:
    """
    Extract text from an image file.

    Args:
        data: Raw image bytes (JPEG, PNG, TIFF, etc.).
        filename: Optional source filename for log context.

    Returns:
        OCR-extracted text, stripped of leading/trailing whitespace.

    Raises:
        PDFParseError: If the image cannot be processed.
    """
    raise PDFParseError(
        "Image parsing is not yet implemented",
        context={"source_file": filename, "bytes": len(data)},
    )
