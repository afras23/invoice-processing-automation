"""
Invoice validation service.

Applies schema presence checks, business rules, and cross-field consistency
checks to extracted invoice fields.  Currency is normalised to ISO 4217.

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

# Tolerance for cross-field total check (2 decimal places of rounding).
_TOTAL_TOLERANCE = 0.02

# Common currency symbol / name → ISO 4217 code.
_CURRENCY_ALIASES: dict[str, str] = {
    "$": "USD",
    "£": "GBP",
    "€": "EUR",
    "us dollar": "USD",
    "usd": "USD",
    "gbp": "GBP",
    "eur": "EUR",
    "dollar": "USD",
    "pound": "GBP",
    "euro": "EUR",
}


def validate_extracted(extracted: ExtractedInvoice) -> ValidationResult:
    """
    Apply business rules to extracted invoice fields.

    Checks:
    - Required fields (vendor, invoice_id, date, amount) are present.
    - amount is greater than zero.
    - date is parseable in a recognised format.
    - due_date (if present) is parseable and not before invoice date.
    - Cross-field: total == sum(line_items) + tax within tolerance.
    - Currency normalised to ISO 4217 (mutated in-place on the model).

    Args:
        extracted: Output from the AI extraction stage.

    Returns:
        ValidationResult with passed=True and an empty errors list when
        all checks succeed; otherwise passed=False with a list of messages.
    """
    validation_errors: list[str] = []

    _normalise_currency(extracted)

    if not extracted.vendor:
        validation_errors.append("vendor is missing")

    if not extracted.invoice_id:
        validation_errors.append("invoice_id is missing")

    invoice_date = _validate_date_field("date", extracted.date, validation_errors)

    if extracted.due_date is not None:
        due_date = _validate_date_field("due_date", extracted.due_date, validation_errors)
        if invoice_date and due_date and due_date < invoice_date:
            validation_errors.append(
                f"due_date '{extracted.due_date}' is before invoice date '{extracted.date}'"
            )

    if extracted.amount is None:
        validation_errors.append("amount is missing")
    elif extracted.amount <= 0:
        validation_errors.append(f"amount must be greater than zero, got {extracted.amount}")

    cross_field_errors = _check_cross_field_totals(extracted)
    validation_errors.extend(cross_field_errors)

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


def normalise_currency(currency_raw: str | None) -> str | None:
    """
    Convert a raw currency string to an ISO 4217 code.

    Args:
        currency_raw: Raw value from the AI (symbol, name, or code).

    Returns:
        Uppercase ISO 4217 code (e.g. "USD"), or the uppercased input if
        no alias matches, or None if the input is None or blank.
    """
    if not currency_raw:
        return None
    lookup_key = currency_raw.strip().lower()
    return _CURRENCY_ALIASES.get(lookup_key, currency_raw.strip().upper())


# ── private helpers ───────────────────────────────────────────────────────────


def _normalise_currency(extracted: ExtractedInvoice) -> None:
    """Mutate extracted.currency in-place to an ISO 4217 code."""
    extracted.currency = normalise_currency(extracted.currency)


def _validate_date_field(
    field_name: str,
    date_value: str | None,
    errors: list[str],
) -> datetime | None:
    """
    Check *date_value* is present and parseable; append to *errors* if not.

    Args:
        field_name: Human-readable name for error messages.
        date_value: The date string to validate (may be None).
        errors: Mutable list to append error messages to.

    Returns:
        Parsed datetime if valid, None otherwise.
    """
    if date_value is None:
        errors.append(f"{field_name} is missing")
        return None
    parsed = _parse_date(date_value)
    if parsed is None:
        errors.append(f"{field_name} '{date_value}' is not a recognised format")
    return parsed


def _check_cross_field_totals(extracted: ExtractedInvoice) -> list[str]:
    """
    Verify that total ≈ sum(line_items) + tax when enough data is present.

    Args:
        extracted: The extracted invoice to check.

    Returns:
        List of cross-field error strings; empty if everything is consistent
        or if there is not enough data to perform the check.
    """
    cross_errors: list[str] = []

    line_items_sum = (
        sum(item.total for item in extracted.line_items) if extracted.line_items else None
    )
    tax = extracted.tax or 0.0
    stated_total = extracted.total or extracted.amount

    if line_items_sum is not None and stated_total is not None:
        expected = round(line_items_sum + tax, 2)
        if abs(expected - stated_total) > _TOTAL_TOLERANCE:
            cross_errors.append(
                f"total {stated_total} does not match "
                f"line_items sum ({line_items_sum:.2f}) + tax ({tax:.2f}) = {expected:.2f}"
            )

    return cross_errors


def _parse_date(date_value: str) -> datetime | None:
    """Return parsed datetime for *date_value*, or None if unparseable."""
    for date_format in _DATE_FORMATS:
        try:
            return datetime.strptime(date_value, date_format)
        except ValueError:
            continue
    return None


def _is_valid_date(date_value: str) -> bool:
    """Return True if *date_value* can be parsed with any known date format."""
    return _parse_date(date_value) is not None
