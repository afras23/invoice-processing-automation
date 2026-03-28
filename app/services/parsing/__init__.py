"""
Document parser factory.

Provides a single entry point — get_parser() — that returns the correct
parser callable for a given file format string.  All parsers return a
ParsedDocument so the rest of the pipeline has a uniform interface.

Supported formats: "pdf", "csv", "image", "text"
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.exceptions import PDFParseError
from app.models.invoice import ParsedDocument
from app.services.parsing.csv_parser import parse_csv
from app.services.parsing.image_parser import parse_image
from app.services.parsing.pdf_parser import parse_document as parse_pdf

_FORMAT_MAP: dict[str, Callable[..., ParsedDocument]] = {
    "pdf": parse_pdf,
    "csv": parse_csv,
    "image": parse_image,
    "text": parse_pdf,  # re-uses pdf_parser's text/bytes fallback path
}

SUPPORTED_FORMATS: frozenset[str] = frozenset(_FORMAT_MAP.keys())


def get_parser(file_format: str) -> Callable[..., ParsedDocument]:
    """
    Return the parser callable for the requested file format.

    Args:
        file_format: One of "pdf", "csv", "image", or "text" (case-insensitive).

    Returns:
        A callable with signature (data: bytes | str, filename: str = "") → ParsedDocument.

    Raises:
        PDFParseError: If *file_format* is not a recognised format.
    """
    normalised = file_format.lower().strip()
    parser = _FORMAT_MAP.get(normalised)
    if parser is None:
        raise PDFParseError(
            f"Unsupported file format '{file_format}'",
            context={
                "file_format": file_format,
                "supported_formats": sorted(SUPPORTED_FORMATS),
            },
        )
    return parser
