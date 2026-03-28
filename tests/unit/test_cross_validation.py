"""
Cross-field validation tests.

Covers: total mismatch, tax mismatch, rounding errors within/outside tolerance,
zero amounts, and consistent/inconsistent multi-field combinations.
"""

from __future__ import annotations

import pytest

from app.models.invoice import ExtractedInvoice, LineItem
from app.services.validation_service import _TOTAL_TOLERANCE, validate_extracted


def _make_invoice(
    *,
    amount: float = 100.0,
    tax: float | None = None,
    total: float | None = None,
    items: list[LineItem] | None = None,
) -> ExtractedInvoice:
    return ExtractedInvoice(
        vendor="Acme Corp",
        invoice_id="INV-001",
        date="2026-03-01",
        amount=amount,
        tax=tax,
        total=total,
        line_items=items or [],
    )


# ── Total mismatch ────────────────────────────────────────────────────────────


def test_total_mismatch_large_fails() -> None:
    """A total that differs from line item sum by >2p is flagged."""
    items = [LineItem(description="A", total=100.0)]
    invoice = _make_invoice(total=200.0, items=items)  # 100 vs 200
    result = validate_extracted(invoice)
    assert not result.passed
    assert any("total" in err for err in result.errors)


def test_total_mismatch_small_within_tolerance_passes() -> None:
    """A total that differs from line item sum by ≤ tolerance (0.02) passes."""
    items = [LineItem(description="A", total=100.00)]
    invoice = _make_invoice(total=100.01, items=items)  # 0.01 difference ≤ 0.02
    result = validate_extracted(invoice)
    assert result.passed


def test_total_mismatch_at_tolerance_boundary_passes() -> None:
    """A mismatch exactly at the tolerance limit is accepted."""
    items = [LineItem(description="A", total=100.00)]
    invoice = _make_invoice(total=100.00 + _TOTAL_TOLERANCE, items=items)
    result = validate_extracted(invoice)
    assert result.passed


def test_total_mismatch_just_over_tolerance_fails() -> None:
    """A mismatch just over the tolerance (0.021) is rejected."""
    items = [LineItem(description="A", total=100.00)]
    # 0.021 > 0.02 tolerance
    invoice = _make_invoice(total=100.021, items=items)
    result = validate_extracted(invoice)
    assert not result.passed


# ── Tax mismatch ──────────────────────────────────────────────────────────────


def test_correct_tax_included_in_total_passes() -> None:
    """line_items_sum + tax == total with positive tax passes."""
    items = [LineItem(description="Service", total=1000.0)]
    invoice = _make_invoice(amount=1200.0, tax=200.0, total=1200.0, items=items)
    result = validate_extracted(invoice)
    assert result.passed


def test_wrong_tax_makes_total_mismatch_fail() -> None:
    """line_items_sum + tax != stated_total is flagged."""
    items = [LineItem(description="Service", total=1000.0)]
    invoice = _make_invoice(amount=1100.0, tax=200.0, total=1100.0, items=items)
    # 1000 + 200 = 1200 ≠ 1100
    result = validate_extracted(invoice)
    assert not result.passed


def test_zero_tax_treated_as_no_tax() -> None:
    """tax=0.0 is equivalent to no tax: only line_items sum matters."""
    items = [LineItem(description="Item", total=500.0)]
    invoice = _make_invoice(amount=500.0, tax=0.0, total=500.0, items=items)
    result = validate_extracted(invoice)
    assert result.passed


# ── Rounding edge cases ───────────────────────────────────────────────────────


def test_floating_point_rounding_within_tolerance_passes() -> None:
    """Floating-point imprecision in line item totals is absorbed by tolerance."""
    # 3 × 33.33 = 99.99, but 3 × (100/3) produces a float with imprecision
    items = [
        LineItem(description="A", total=33.33),
        LineItem(description="B", total=33.33),
        LineItem(description="C", total=33.34),
    ]
    invoice = _make_invoice(total=100.00, items=items)  # 33.33+33.33+33.34 = 100.00
    result = validate_extracted(invoice)
    assert result.passed


def test_multiple_items_rounding_accumulation() -> None:
    """Many items with rounding-prone values still pass when sum is correct."""
    items = [LineItem(description=f"Item {i}", total=0.10) for i in range(10)]
    invoice = _make_invoice(total=1.00, items=items)  # 10 × 0.10 = 1.00
    result = validate_extracted(invoice)
    assert result.passed


# ── Zero and edge amounts ─────────────────────────────────────────────────────


def test_zero_amount_fails_validation() -> None:
    """amount=0 fails the amount > 0 rule regardless of line items."""
    invoice = _make_invoice(amount=0.0)
    result = validate_extracted(invoice)
    assert not result.passed
    assert any("zero" in err or "greater" in err for err in result.errors)


def test_very_small_positive_amount_passes() -> None:
    """amount=0.01 (minimum viable) is accepted."""
    invoice = _make_invoice(amount=0.01)
    result = validate_extracted(invoice)
    # May still fail for other missing fields, but not for the amount itself
    amount_errors = [e for e in result.errors if "amount" in e and "zero" in e]
    assert len(amount_errors) == 0


# ── Combined cross-field checks ───────────────────────────────────────────────


def test_multiple_cross_field_errors_all_reported() -> None:
    """When both total mismatch and date error exist, both are reported."""
    items = [LineItem(description="Item", total=50.0)]
    invoice = ExtractedInvoice(
        vendor="Acme",
        invoice_id="INV-1",
        date="not-a-date",
        amount=100.0,
        total=100.0,  # mismatch: 50 ≠ 100
        line_items=items,
    )
    result = validate_extracted(invoice)
    assert not result.passed
    assert len(result.errors) >= 2  # date error + total mismatch


@pytest.mark.parametrize(
    "line_total,invoice_total,should_pass",
    [
        (100.0, 100.0, True),
        (100.0, 100.02, True),  # within tolerance
        (100.0, 100.03, False),  # just over tolerance
        (100.0, 50.0, False),  # large mismatch
        (100.0, 150.0, False),  # overstated total
    ],
)
def test_cross_field_tolerance_parametrized(
    line_total: float, invoice_total: float, should_pass: bool
) -> None:
    """Parametrised check of cross-field total matching with various tolerances."""
    items = [LineItem(description="Item", total=line_total)]
    invoice = _make_invoice(total=invoice_total, items=items)
    result = validate_extracted(invoice)
    assert result.passed == should_pass
