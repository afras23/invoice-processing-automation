"""
Image invoice parser.

Loads image files (JPEG, PNG, TIFF, BMP, WEBP) using Pillow to confirm
they are valid images, then flags them for OCR processing.

OCR is not implemented here — the ParsedDocument is returned with
needs_ocr=True and a brief placeholder text so the calling pipeline
can route the document to an OCR stage (pytesseract, Google Vision, etc.)
without crashing.
"""

from __future__ import annotations

import hashlib
import logging
from io import BytesIO

from app.core.exceptions import PDFParseError
from app.models.invoice import ParsedDocument

logger = logging.getLogger(__name__)


def parse_image(data: bytes, filename: str = "") -> ParsedDocument:
    """
    Validate an image file and flag it for OCR processing.

    Pillow is used to open the image and extract basic metadata
    (format, dimensions).  The returned ParsedDocument has needs_ocr=True
    and a placeholder text so the pipeline does not crash while OCR is
    not yet wired up.

    Args:
        data: Raw image bytes (JPEG, PNG, TIFF, BMP, WEBP, etc.).
        filename: Optional source filename for log context.

    Returns:
        ParsedDocument with needs_ocr=True and image metadata as text.

    Raises:
        PDFParseError: If Pillow cannot open the image.
    """
    try:
        from PIL import Image  # noqa: PLC0415 — lazy import to keep Pillow optional

        image = Image.open(BytesIO(data))
        image_format = image.format or "UNKNOWN"
        width, height = image.size
    except ImportError as exc:
        raise PDFParseError(
            "Pillow is required for image parsing — install it with: pip install Pillow",
            context={"source_file": filename},
        ) from exc
    except Exception as exc:
        raise PDFParseError(
            f"Failed to open image '{filename}'",
            context={"source_file": filename, "error": str(exc)},
        ) from exc

    placeholder_text = (
        f"[IMAGE: {filename or 'unknown'} | format={image_format} | {width}x{height}px]"
    )
    logger.info(
        "Image parsed — flagged for OCR",
        extra={
            "source_file": filename,
            "image_format": image_format,
            "width": width,
            "height": height,
        },
    )
    return ParsedDocument(
        text=placeholder_text,
        content_hash=_hash(placeholder_text),
        format="image",
        needs_ocr=True,
        filename=filename,
    )


def _hash(text: str) -> str:
    normalised = " ".join(text.split())
    return hashlib.sha256(normalised.encode()).hexdigest()
