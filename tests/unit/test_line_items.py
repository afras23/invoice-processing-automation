"""
Line item edge case tests.

Covers: no line items, 50+ line items, special characters in descriptions,
zero-quantity items, and items with only totals (no unit price).
"""

from __future__ import annotations

import pytest

from app.models.invoice import ExtractedInvoice, LineItem
from app.services.validation_service import validate_extracted


def _invoice_with_items(items: list[LineItem], total: float) -> ExtractedInvoice:
    """Build a minimal ExtractedInvoice with the given line items and total."""
    return ExtractedInvoice(
        vendor="Acme Corp",
        invoice_id="INV-001",
        date="2026-03-01",
        amount=total,
        total=total,
        line_items=items,
    )


# ── No line items ─────────────────────────────────────────────────────────────


def test_no_line_items_passes_validation() -> None:
    """An invoice with zero line items passes cross-field validation (nothing to check)."""
    invoice = _invoice_with_items([], 500.0)
    result = validate_extracted(invoice)
    assert result.passed


def test_no_line_items_has_no_cross_field_error() -> None:
    """Cross-field check is skipped entirely when no line items are present."""
    invoice = _invoice_with_items([], 100.0)
    result = validate_extracted(invoice)
    assert not any("line_items" in err for err in result.errors)


# ── Many line items ───────────────────────────────────────────────────────────


def test_fifty_line_items_all_sum_correctly() -> None:
    """50 line items summing to the stated total pass cross-field validation."""
    items = [LineItem(description=f"Item {i}", total=10.0) for i in range(50)]
    invoice = _invoice_with_items(items, 500.0)
    result = validate_extracted(invoice)
    assert result.passed


def test_fifty_line_items_wrong_total_fails() -> None:
    """50 items summing to the wrong total are caught by cross-field validation."""
    items = [LineItem(description=f"Item {i}", total=10.0) for i in range(50)]
    invoice = _invoice_with_items(items, 999.0)  # should be 500.0
    result = validate_extracted(invoice)
    assert not result.passed
    assert any("total" in err for err in result.errors)


def test_single_line_item_matches_total() -> None:
    """A single line item whose total equals the invoice total passes."""
    items = [LineItem(description="Consulting", total=1500.0)]
    invoice = _invoice_with_items(items, 1500.0)
    result = validate_extracted(invoice)
    assert result.passed


# ── Special characters in descriptions ───────────────────────────────────────


@pytest.mark.parametrize(
    "description",
    [
        "Software licence & support",
        'Professional services — Q1 "Design" work',
        "Développement / Développeur",
        "Консалтинг (Consulting)",
        "Hardware: Server × 2 @ $500",
        "<script>alert('xss')</script>",
        "Item\twith\ttabs",
        "Multi\nline\ndescription",
        "Emoji description 🧾",
        "A" * 500,  # very long description
    ],
)
def test_special_characters_in_description_do_not_fail_validation(
    description: str,
) -> None:
    """Line item descriptions with special/unicode characters do not break validation."""
    items = [LineItem(description=description, total=100.0)]
    invoice = _invoice_with_items(items, 100.0)
    result = validate_extracted(invoice)
    # Validation may fail on business rules, but not due to description content
    assert not any("description" in err.lower() for err in result.errors)


# ── Items with missing optional fields ────────────────────────────────────────


def test_line_item_without_quantity_or_unit_price_uses_total() -> None:
    """A LineItem with only a total (no quantity/unit_price) is valid."""
    items = [LineItem(description="Fixed-fee service", total=750.0)]
    invoice = _invoice_with_items(items, 750.0)
    result = validate_extracted(invoice)
    assert result.passed


def test_line_item_with_quantity_and_unit_price() -> None:
    """quantity × unit_price is not re-validated; only totals are checked."""
    items = [
        LineItem(description="Widget", quantity=3, unit_price=25.0, total=75.0),
        LineItem(description="Gadget", quantity=2, unit_price=12.50, total=25.0),
    ]
    invoice = _invoice_with_items(items, 100.0)
    result = validate_extracted(invoice)
    assert result.passed


# ── Line items with tax ───────────────────────────────────────────────────────


def test_line_items_plus_tax_equals_total_passes() -> None:
    """sum(line_items) + tax == total is accepted."""
    items = [LineItem(description="Service", total=1000.0)]
    invoice = ExtractedInvoice(
        vendor="Acme",
        invoice_id="INV-1",
        date="2026-03-01",
        amount=1200.0,
        subtotal=1000.0,
        tax=200.0,
        total=1200.0,
        line_items=items,
    )
    result = validate_extracted(invoice)
    assert result.passed
