"""
Export service — multi-format accounting export.

Converts pipeline results and invoice models into formats ready for import
into accounting systems.

Supported formats:
  generic_csv      — generic pipeline CSV (vendor, invoice_id, date, amount…)
  xero_csv         — Xero Bills CSV import format
  quickbooks_csv   — QuickBooks Online CSV import format
  google_sheets    — append to Google Sheets via the SheetsClient
  xero_json        — Xero API payload dict (legacy, kept for integrations)
  quickbooks_iif   — QuickBooks Desktop IIF format (legacy)
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime

from app.models.invoice import Invoice, PipelineResult

logger = logging.getLogger(__name__)

# ── Generic CSV ───────────────────────────────────────────────────────────────

_GENERIC_CSV_HEADERS = [
    "vendor",
    "invoice_id",
    "date",
    "amount",
    "currency",
    "confidence",
    "validation_passed",
    "exported_at",
]


def to_csv_row(pipeline_result: PipelineResult) -> list[str]:
    """
    Convert a PipelineResult to a flat generic CSV row.

    Args:
        pipeline_result: Completed pipeline output with status "processed".

    Returns:
        List of string values corresponding to _GENERIC_CSV_HEADERS.
    """
    extracted = pipeline_result.extracted
    confidence = pipeline_result.confidence
    validation = pipeline_result.validation
    exported_at = datetime.now(UTC).isoformat()

    if extracted is None or confidence is None or validation is None:
        return ["", "", "", "", "", "", "NO", exported_at]

    total = extracted.total or extracted.amount
    return [
        extracted.vendor or "",
        extracted.invoice_id or "",
        extracted.date or "",
        str(total) if total is not None else "",
        extracted.currency or "",
        str(confidence.score),
        "YES" if validation.passed else "NO",
        exported_at,
    ]


def to_csv_string(pipeline_results: list[PipelineResult]) -> str:
    """
    Serialise a list of PipelineResults to a generic CSV string with headers.

    Args:
        pipeline_results: One or more processed pipeline results.

    Returns:
        UTF-8 CSV string including a header row.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_GENERIC_CSV_HEADERS)
    for pipeline_result in pipeline_results:
        writer.writerow(to_csv_row(pipeline_result))
    logger.info("Exported to generic CSV", extra={"row_count": len(pipeline_results)})
    return buffer.getvalue()


# ── Xero CSV ──────────────────────────────────────────────────────────────────

_XERO_CSV_HEADERS = [
    "*ContactName",
    "*InvoiceNumber",
    "*InvoiceDate",
    "*DueDate",
    "*Description",
    "*Quantity",
    "*UnitAmount",
    "*AccountCode",
    "*TaxType",
    "Currency",
]


def to_xero_csv(invoice: Invoice) -> str:
    """
    Format an Invoice as a Xero Bills CSV import string.

    Args:
        invoice: Fully populated Invoice model.

    Returns:
        UTF-8 CSV string ready for import into Xero.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_XERO_CSV_HEADERS)

    line_items = invoice.line_items or []
    if not line_items:
        writer.writerow(
            [
                invoice.vendor,
                invoice.invoice_number,
                invoice.invoice_date,
                "",
                "Invoice payment",
                1,
                invoice.total_amount,
                "200",
                "NONE",
                invoice.currency,
            ]
        )
    else:
        for line_item in line_items:
            writer.writerow(
                [
                    invoice.vendor,
                    invoice.invoice_number,
                    invoice.invoice_date,
                    "",
                    line_item.description,
                    line_item.quantity or 1,
                    line_item.unit_price or line_item.total,
                    "200",
                    "NONE",
                    invoice.currency,
                ]
            )

    logger.info("Exported to Xero CSV", extra={"invoice_number": invoice.invoice_number})
    return buffer.getvalue()


# ── QuickBooks CSV ────────────────────────────────────────────────────────────

_QB_CSV_HEADERS = [
    "Vendor",
    "Invoice Number",
    "Invoice Date",
    "Due Date",
    "Description",
    "Amount",
    "Currency",
    "Account",
]


def to_quickbooks_csv(invoice: Invoice) -> str:
    """
    Format an Invoice as a QuickBooks Online CSV import string.

    Args:
        invoice: Fully populated Invoice model.

    Returns:
        UTF-8 CSV string ready for import into QuickBooks Online.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_QB_CSV_HEADERS)

    line_items = invoice.line_items or []
    if not line_items:
        writer.writerow(
            [
                invoice.vendor,
                invoice.invoice_number,
                invoice.invoice_date,
                "",
                "Invoice payment",
                invoice.total_amount,
                invoice.currency,
                "Accounts Payable",
            ]
        )
    else:
        for line_item in line_items:
            writer.writerow(
                [
                    invoice.vendor,
                    invoice.invoice_number,
                    invoice.invoice_date,
                    "",
                    line_item.description,
                    line_item.total,
                    invoice.currency,
                    "Accounts Payable",
                ]
            )

    logger.info(
        "Exported to QuickBooks CSV",
        extra={"invoice_number": invoice.invoice_number},
    )
    return buffer.getvalue()


# ── QuickBooks IIF (legacy) ───────────────────────────────────────────────────


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
        f"SPL\tBILL\t{invoice.invoice_date}\tExpenses\t{invoice.vendor}\t{invoice.total_amount}",
        "ENDTRNS",
    ]
    logger.info("Exported to QuickBooks IIF", extra={"invoice_number": invoice.invoice_number})
    return "\n".join(lines)


# ── Xero JSON payload (legacy) ────────────────────────────────────────────────


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
    logger.info("Built Xero JSON payload", extra={"invoice_number": invoice.invoice_number})
    return xero_payload


# ── Google Sheets export ──────────────────────────────────────────────────────


async def export_to_sheets(
    pipeline_result: PipelineResult,
    sheets_client: object,
) -> None:
    """
    Append a processed invoice row to Google Sheets via the async SheetsClient.

    Args:
        pipeline_result: Completed pipeline result to export.
        sheets_client: An instance of SheetsClient (or compatible mock).
    """
    extracted = pipeline_result.extracted
    if extracted is None:
        return

    total = extracted.total or extracted.amount
    row = [
        extracted.vendor or "",
        extracted.invoice_id or "",
        extracted.date or "",
        str(total) if total is not None else "",
        extracted.currency or "",
        str(pipeline_result.confidence.score) if pipeline_result.confidence else "",
        datetime.now(UTC).isoformat(),
    ]
    await sheets_client.append_row(row)  # type: ignore[attr-defined]
    logger.info(
        "Invoice exported to Google Sheets",
        extra={"vendor": extracted.vendor, "invoice_id": extracted.invoice_id},
    )
