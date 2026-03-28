"""
CSV invoice parser.

Converts CSV-formatted invoice data into a normalised text representation
suitable for AI extraction.  Handles common delimiters (auto-detected via
csv.Sniffer) and encodings (UTF-8 with latin-1 fallback).
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging

from app.core.exceptions import PDFParseError
from app.models.invoice import ParsedDocument

logger = logging.getLogger(__name__)

_CANDIDATE_ENCODINGS = ["utf-8", "latin-1", "cp1252"]


def parse_csv(data: bytes | str, filename: str = "") -> ParsedDocument:
    """
    Convert CSV invoice data to a ParsedDocument.

    Each CSV row is rendered as "key: value" pairs (using the header row
    as keys) so the AI extraction prompt can process it naturally.
    The delimiter is auto-detected via csv.Sniffer; encoding is probed
    in order: UTF-8 → latin-1 → cp1252.

    Args:
        data: Raw CSV bytes or pre-decoded string.
        filename: Optional source filename for log context.

    Returns:
        ParsedDocument with plain-text CSV representation, content hash,
        and format="csv".

    Raises:
        PDFParseError: If the CSV cannot be decoded or parsed.
    """
    csv_text = _decode_csv_bytes(data, filename)
    delimiter = _detect_delimiter(csv_text, filename)

    try:
        reader = csv.DictReader(io.StringIO(csv_text), delimiter=delimiter)
        rows = list(reader)
    except csv.Error as exc:
        raise PDFParseError(
            f"Failed to parse CSV '{filename}'",
            context={"source_file": filename, "error": str(exc)},
        ) from exc

    if not rows:
        logger.warning("CSV file contained no data rows", extra={"source_file": filename})
        stripped = csv_text.strip()
        return ParsedDocument(
            text=stripped,
            content_hash=_hash(stripped),
            format="csv",
            filename=filename,
        )

    lines: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        lines.append(f"--- Row {row_index} ---")
        for field_name, field_value in row.items():
            if field_value:
                lines.append(f"{field_name}: {field_value}")

    csv_repr = "\n".join(lines)
    logger.info(
        "CSV parsed",
        extra={"source_file": filename, "rows": len(rows), "delimiter": repr(delimiter)},
    )
    return ParsedDocument(
        text=csv_repr,
        content_hash=_hash(csv_repr),
        format="csv",
        filename=filename,
    )


# ── private helpers ───────────────────────────────────────────────────────────


def _hash(text: str) -> str:
    normalised = " ".join(text.split())
    return hashlib.sha256(normalised.encode()).hexdigest()


def _decode_csv_bytes(data: bytes | str, filename: str) -> str:
    """
    Decode CSV bytes to a string, probing candidate encodings.

    Args:
        data: Raw bytes or string (returned unchanged if already a string).
        filename: Used for log context on failure.

    Returns:
        Decoded CSV string.

    Raises:
        PDFParseError: If no candidate encoding succeeds.
    """
    if isinstance(data, str):
        return data

    for encoding in _CANDIDATE_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue

    raise PDFParseError(
        f"Could not decode CSV '{filename}' with any supported encoding",
        context={"source_file": filename, "tried_encodings": _CANDIDATE_ENCODINGS},
    )


def _detect_delimiter(csv_text: str, filename: str) -> str:
    """
    Infer the CSV delimiter using csv.Sniffer, defaulting to comma.

    Args:
        csv_text: Decoded CSV string.
        filename: Used for log context.

    Returns:
        Single-character delimiter string.
    """
    sample = csv_text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        return dialect.delimiter
    except csv.Error:
        logger.debug(
            "csv.Sniffer could not detect delimiter, defaulting to comma",
            extra={"source_file": filename},
        )
        return ","
