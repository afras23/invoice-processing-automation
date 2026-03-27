"""
CSV invoice parser.

Converts CSV-formatted invoice data into a normalised text representation
suitable for AI extraction.  Handles common delimiters and encodings.
"""

from __future__ import annotations

import csv
import io
import logging

from app.core.exceptions import PDFParseError

logger = logging.getLogger(__name__)


def parse_csv(data: bytes | str, filename: str = "") -> str:
    """
    Convert CSV invoice data to a plain-text representation.

    Each CSV row is rendered as "key: value" pairs (using the header row
    as keys) so the AI extraction prompt can process it naturally.

    Args:
        data: Raw CSV bytes or string.
        filename: Optional source filename for log context.

    Returns:
        Normalised plain-text representation of the CSV content.

    Raises:
        PDFParseError: If the CSV cannot be parsed.
    """
    if isinstance(data, bytes):
        csv_text = data.decode("utf-8", errors="replace")
    else:
        csv_text = data

    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)
    except csv.Error as exc:
        raise PDFParseError(
            f"Failed to parse CSV '{filename}'",
            context={"source_file": filename, "error": str(exc)},
        ) from exc

    if not rows:
        logger.warning("CSV file contained no data rows", extra={"source_file": filename})
        return csv_text.strip()

    lines: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        lines.append(f"--- Row {row_index} ---")
        for field_name, field_value in row.items():
            if field_value:
                lines.append(f"{field_name}: {field_value}")

    logger.info(
        "CSV parsed",
        extra={"source_file": filename, "rows": len(rows)},
    )
    return "\n".join(lines)
