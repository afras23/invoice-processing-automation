"""
Invoice validation service.

Applies schema presence checks and business rules to extracted invoice fields.
All validation logic lives here — routes and the extraction pipeline delegate
to these functions rather than reimplementing checks.
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.config import settings
from app.models.invoice import ExtractedInvoice, Invoice, ValidationResult

logger = logging.getLogger(__name__)

# Date formats the validator will accept.
_DATE_FORMATS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%d %B %Y",
    "%B %d, %Y",
    "%d %b %Y",
]


def validate_extracted(extracted: ExtractedInvoice) -> ValidationResult:
    """
    Apply business rules to extracted invoice fields.

    Checks:
    - Required fields (vendor, invoice_id, date, amount) are present.
    - amount is greater than zero.
    - date is parseable in a recognised format.

    Args:
        extracted: Output from the AI extraction stage.

    Returns:
        ValidationResult with passed=True and an empty errors list when
        all checks succeed; otherwise passed=False with a list of messages.
    """
    validation_errors: list[str] = []

    if not extracted.vendor:
        validation_errors.append("vendor is missing")

    if not extracted.invoice_id:
        validation_errors.append("invoice_id is missing")

    if extracted.date is None:
        validation_errors.append("date is missing")
    elif not _is_valid_date(extracted.date):
        validation_errors.append(f"date '{extracted.date}' is not a recognised format")

    if extracted.amount is None:
        validation_errors.append("amount is missing")
    elif extracted.amount <= 0:
        validation_errors.append(f"amount must be greater than zero, got {extracted.amount}")

    validation_result = ValidationResult(
        passed=len(validation_errors) == 0,
        errors=validation_errors,
    )

    if not validation_result.passed:
        logger.warning(
            "Extracted invoice failed validation",
            extra={"errors": validation_errors},
        )

    return validation_result


def requires_approval(invoice_amount: float) -> bool:
    """
    Return True if the amount exceeds the configured approval threshold.

    Args:
        invoice_amount: The invoice total to check.

    Returns:
        True if manual approval is required, False otherwise.
    """
    return invoice_amount > settings.approval_threshold


def validate_invoice(invoice: Invoice) -> list[str]:
    """
    Validate a rich Invoice model (used by the HTTP route for the full schema).

    Args:
        invoice: Fully populated Invoice model from the integrations path.

    Returns:
        List of validation issue strings; empty list means the invoice is valid.
    """
    validation_issues: list[str] = []

    if invoice.total_amount <= 0:
        validation_issues.append("Invoice total must be greater than zero")

    if not invoice.line_items:
        validation_issues.append("Invoice has no line items")

    if validation_issues:
        logger.warning(
            "Invoice failed validation",
            extra={
                "invoice_number": invoice.invoice_number,
                "issues": validation_issues,
            },
        )

    return validation_issues


# ── private helpers ───────────────────────────────────────────────────────────


def _is_valid_date(date_value: str) -> bool:
    """Return True if *date_value* can be parsed with any known date format."""
    for date_format in _DATE_FORMATS:
        try:
            datetime.strptime(date_value, date_format)
            return True
        except ValueError:
            continue
    return False
