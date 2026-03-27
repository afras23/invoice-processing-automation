"""
Export service — accounting format templates.

Converts pipeline results and invoice models into formats suitable for
accounting systems: CSV rows, JSON payloads, and accounting-software
specific templates (QuickBooks, Xero, Sage).

All formatters return plain Python structures (list or dict) so they can
be serialised by the caller into CSV, JSON, or any other wire format.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime

from app.models.invoice import Invoice, PipelineResult

logger = logging.getLogger(__name__)

# ── CSV export ────────────────────────────────────────────────────────────────

_CSV_HEADERS = [
    "vendor",
    "invoice_id",
    "date",
    "amount",
    "confidence",
    "validation_passed",
    "exported_at",
]


def to_csv_row(pipeline_result: PipelineResult) -> list[str]:
    """
    Convert a PipelineResult to a flat CSV row.

    Args:
        pipeline_result: Completed pipeline output with status "processed".

    Returns:
        List of string values corresponding to CSV_HEADERS.
    """
    extracted = pipeline_result.extracted
    confidence = pipeline_result.confidence
    validation = pipeline_result.validation

    exported_at = datetime.now(UTC).isoformat()

    if extracted is None or confidence is None or validation is None:
        return ["", "", "", "", "", "NO", exported_at]

    return [
        extracted.vendor or "",
        extracted.invoice_id or "",
        extracted.date or "",
        str(extracted.amount) if extracted.amount is not None else "",
        str(confidence.score),
        "YES" if validation.passed else "NO",
        exported_at,
    ]


def to_csv_string(pipeline_results: list[PipelineResult]) -> str:
    """
    Serialise a list of PipelineResults to a CSV string with headers.

    Args:
        pipeline_results: One or more processed pipeline results.

    Returns:
        UTF-8 CSV string including a header row.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_HEADERS)
    for pipeline_result in pipeline_results:
        writer.writerow(to_csv_row(pipeline_result))

    logger.info(
        "Exported pipeline results to CSV",
        extra={"row_count": len(pipeline_results)},
    )
    return buffer.getvalue()


# ── QuickBooks IIF template ───────────────────────────────────────────────────


def to_quickbooks_iif(invoice: Invoice) -> str:
    """
    Format an Invoice as a QuickBooks IIF import string.

    Args:
        invoice: Fully populated Invoice model.

    Returns:
        IIF-formatted string ready for import into QuickBooks Desktop.
    """
    lines = [
        "!TRNS\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM",
        "!SPL\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT",
        "!ENDTRNS",
        (
            f"TRNS\tBILL\t{invoice.invoice_date}\tAccounts Payable"
            f"\t{invoice.vendor}\t-{invoice.total_amount}\t{invoice.invoice_number}"
        ),
        (f"SPL\tBILL\t{invoice.invoice_date}\tExpenses\t{invoice.vendor}\t{invoice.total_amount}"),
        "ENDTRNS",
    ]

    logger.info(
        "Exported invoice to QuickBooks IIF",
        extra={"invoice_number": invoice.invoice_number},
    )
    return "\n".join(lines)


# ── Xero JSON template ────────────────────────────────────────────────────────


def to_xero_payload(invoice: Invoice) -> dict:
    """
    Build a Xero API-compatible invoice payload dict.

    Args:
        invoice: Fully populated Invoice model.

    Returns:
        Dict matching the Xero Invoices API schema.
    """
    xero_payload: dict = {
        "Type": "ACCPAY",
        "Contact": {"Name": invoice.vendor},
        "Date": invoice.invoice_date,
        "InvoiceNumber": invoice.invoice_number,
        "CurrencyCode": invoice.currency or "GBP",
        "Status": "DRAFT",
        "LineItems": [
            {
                "Description": line_item.description,
                "Quantity": line_item.quantity or 1,
                "UnitAmount": line_item.unit_price or line_item.total,
                "LineAmount": line_item.total,
            }
            for line_item in invoice.line_items
        ],
    }

    logger.info(
        "Built Xero payload",
        extra={"invoice_number": invoice.invoice_number},
    )
    return xero_payload
