"""
Invoice validation service.

validate_extracted() is the pipeline-facing function.
validate_invoice() / requires_approval() are retained for the HTTP route.
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.config import settings
from app.models.invoice import ExtractedInvoice, Invoice, ValidationResult

logger = logging.getLogger(__name__)

# Date formats the validator will accept
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
    - date is parseable in a known format.

    Args:
        extracted: Output from the extraction stage.

    Returns:
        ValidationResult with passed=True and an empty errors list when
        all checks succeed.
    """
    errors: list[str] = []

    if not extracted.vendor:
        errors.append("vendor is missing")

    if not extracted.invoice_id:
        errors.append("invoice_id is missing")

    if extracted.date is None:
        errors.append("date is missing")
    elif not _is_valid_date(extracted.date):
        errors.append(f"date '{extracted.date}' is not a recognised format")

    if extracted.amount is None:
        errors.append("amount is missing")
    elif extracted.amount <= 0:
        errors.append(f"amount must be greater than zero, got {extracted.amount}")

    result = ValidationResult(passed=len(errors) == 0, errors=errors)

    if not result.passed:
        logger.warning(
            "Extracted invoice failed validation",
            extra={"errors": errors},
        )

    return result


def requires_approval(amount: float) -> bool:
    """Return True if the amount exceeds the configured approval threshold."""
    return amount > settings.approval_threshold


def validate_invoice(invoice: Invoice) -> list[str]:
    """Legacy validator used by the HTTP route for the richer Invoice model."""
    issues: list[str] = []

    if invoice.total_amount <= 0:
        issues.append("Invoice total must be greater than zero")

    if not invoice.line_items:
        issues.append("Invoice has no line items")

    if issues:
        logger.warning(
            "Invoice failed validation",
            extra={"invoice_number": invoice.invoice_number, "issues": issues},
        )

    return issues


# ── private helpers ───────────────────────────────────────────────────────────

def _is_valid_date(value: str) -> bool:
    """Return True if *value* can be parsed with any known date format."""
    for fmt in _DATE_FORMATS:
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    return False
