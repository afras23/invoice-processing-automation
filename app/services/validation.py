"""
Invoice validation service.

Applies business rules to extracted invoice data.
"""

import logging

from app.config import settings
from app.models.invoice import Invoice

logger = logging.getLogger(__name__)


def validate_invoice(invoice: Invoice) -> list[str]:
    """
    Apply business rule validation to an invoice.

    Args:
        invoice: Parsed Invoice model.

    Returns:
        List of issue descriptions. Empty list means the invoice is clean.
    """
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


def requires_approval(amount: float) -> bool:
    """
    Determine whether an invoice requires manual approval.

    Args:
        amount: Invoice total amount.

    Returns:
        True if the amount exceeds the configured approval threshold.
    """
    return amount > settings.approval_threshold
