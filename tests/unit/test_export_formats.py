"""
Export format tests.

Verifies that each export format (Generic CSV, Xero CSV, QuickBooks CSV)
produces structurally valid output with correct headers and row values.
"""

from __future__ import annotations

import csv
import io

import pytest

from app.models.invoice import (
    ConfidenceResult,
    ExtractedInvoice,
    Invoice,
    LineItem,
    PipelineResult,
    ValidationResult,
)
from app.services.export_service import (
    to_csv_string,
    to_quickbooks_csv,
    to_xero_csv,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


_DEFAULT_LINE_ITEMS = [
    LineItem(description="Consulting", quantity=10, unit_price=150.0, total=1500.0)
]


def _invoice(
    *,
    vendor: str = "Acme Corp",
    invoice_number: str = "INV-001",
    currency: str = "GBP",
    total: float = 1500.0,
    line_items: list[LineItem] | None = _DEFAULT_LINE_ITEMS,
) -> Invoice:
    return Invoice(
        vendor=vendor,
        invoice_number=invoice_number,
        invoice_date="2026-03-01",
        currency=currency,
        total_amount=total,
        line_items=line_items if line_items is not None else [],
    )


def _pipeline_result(
    vendor: str = "Acme Corp",
    invoice_id: str = "INV-001",
    amount: float = 1500.0,
    currency: str = "USD",
) -> PipelineResult:
    return PipelineResult(
        status="processed",
        content_hash="abc123",
        extracted=ExtractedInvoice(
            vendor=vendor,
            invoice_id=invoice_id,
            date="2026-03-01",
            amount=amount,
            currency=currency,
        ),
        validation=ValidationResult(passed=True, errors=[]),
        confidence=ConfidenceResult(score=0.95, completeness=1.0, validation_score=1.0),
    )


# ── Generic CSV ───────────────────────────────────────────────────────────────


def test_generic_csv_produces_parseable_csv() -> None:
    """to_csv_string output is valid CSV parseable by csv.DictReader."""
    output = to_csv_string([_pipeline_result()])
    rows = list(csv.DictReader(io.StringIO(output)))
    assert len(rows) == 1


def test_generic_csv_multiple_rows() -> None:
    """Multiple PipelineResults produce multiple rows (plus header)."""
    results = [_pipeline_result(vendor=f"Vendor {i}", invoice_id=f"INV-{i}") for i in range(5)]
    output = to_csv_string(results)
    rows = list(csv.DictReader(io.StringIO(output)))
    assert len(rows) == 5


def test_generic_csv_currency_column_present() -> None:
    """The 'currency' column appears in generic CSV output."""
    output = to_csv_string([_pipeline_result(currency="GBP")])
    reader = csv.DictReader(io.StringIO(output))
    assert "currency" in (reader.fieldnames or [])
    rows = list(reader)
    assert rows[0]["currency"] == "GBP"


def test_generic_csv_empty_results_only_headers() -> None:
    """An empty list produces only a header row."""
    output = to_csv_string([])
    lines = [line for line in output.splitlines() if line.strip()]
    assert len(lines) == 1  # just the header


def test_generic_csv_validation_passed_shown_as_yes_no() -> None:
    """validation_passed column shows 'YES' for passed, 'NO' for failed."""
    passed = PipelineResult(
        status="processed",
        content_hash="h1",
        extracted=ExtractedInvoice(vendor="A", invoice_id="I1", date="2026-03-01", amount=100.0),
        validation=ValidationResult(passed=True, errors=[]),
        confidence=ConfidenceResult(score=0.9, completeness=1.0, validation_score=1.0),
    )
    failed = PipelineResult(
        status="processed",
        content_hash="h2",
        extracted=ExtractedInvoice(vendor="B", invoice_id="I2", date="2026-03-01", amount=200.0),
        validation=ValidationResult(passed=False, errors=["vendor is missing"]),
        confidence=ConfidenceResult(score=0.5, completeness=0.5, validation_score=0.0),
    )
    output = to_csv_string([passed, failed])
    rows = list(csv.DictReader(io.StringIO(output)))
    assert rows[0]["validation_passed"] == "YES"
    assert rows[1]["validation_passed"] == "NO"


# ── Xero CSV ──────────────────────────────────────────────────────────────────


def test_xero_csv_produces_parseable_csv() -> None:
    """to_xero_csv output is valid CSV."""
    output = to_xero_csv(_invoice())
    rows = list(csv.DictReader(io.StringIO(output)))
    assert len(rows) >= 1


def test_xero_csv_with_multiple_line_items_produces_multiple_rows() -> None:
    """Each line item produces its own row in the Xero CSV."""
    items = [
        LineItem(description="Consulting", quantity=5, unit_price=200.0, total=1000.0),
        LineItem(description="Expenses", quantity=1, unit_price=500.0, total=500.0),
    ]
    output = to_xero_csv(_invoice(line_items=items))
    rows = list(csv.DictReader(io.StringIO(output)))
    assert len(rows) == 2


def test_xero_csv_no_line_items_produces_one_row() -> None:
    """Invoice with no line items produces a single fallback row."""
    output = to_xero_csv(_invoice(line_items=[]))
    rows = list(csv.DictReader(io.StringIO(output)))
    assert len(rows) == 1
    assert rows[0]["*Description"] == "Invoice payment"


def test_xero_csv_currency_in_output() -> None:
    """Currency code appears in the Xero CSV Currency column."""
    output = to_xero_csv(_invoice(currency="EUR"))
    rows = list(csv.DictReader(io.StringIO(output)))
    assert rows[0]["Currency"] == "EUR"


@pytest.mark.parametrize("currency", ["USD", "GBP", "EUR", "JPY"])
def test_xero_csv_various_currencies(currency: str) -> None:
    """Xero CSV is generated for all major currencies."""
    output = to_xero_csv(_invoice(currency=currency))
    rows = list(csv.DictReader(io.StringIO(output)))
    assert rows[0]["Currency"] == currency


# ── QuickBooks CSV ────────────────────────────────────────────────────────────


def test_quickbooks_csv_produces_parseable_csv() -> None:
    """to_quickbooks_csv output is valid CSV."""
    output = to_quickbooks_csv(_invoice())
    rows = list(csv.DictReader(io.StringIO(output)))
    assert len(rows) >= 1


def test_quickbooks_csv_no_line_items_single_row() -> None:
    """Invoice with no line items produces one summary row."""
    output = to_quickbooks_csv(_invoice(line_items=[]))
    rows = list(csv.DictReader(io.StringIO(output)))
    assert len(rows) == 1
    assert rows[0]["Description"] == "Invoice payment"


def test_quickbooks_csv_with_line_items_per_line_row() -> None:
    """Each line item produces its own QuickBooks row."""
    items = [
        LineItem(description="Widget", total=100.0),
        LineItem(description="Service", total=200.0),
        LineItem(description="Support", total=50.0),
    ]
    output = to_quickbooks_csv(_invoice(line_items=items))
    rows = list(csv.DictReader(io.StringIO(output)))
    assert len(rows) == 3


def test_quickbooks_csv_vendor_name_preserved() -> None:
    """Vendor name with special characters is preserved in QuickBooks CSV."""
    output = to_quickbooks_csv(_invoice(vendor="O'Brien & Partners"))
    rows = list(csv.DictReader(io.StringIO(output)))
    assert rows[0]["Vendor"] == "O'Brien & Partners"


def test_quickbooks_csv_account_column_present() -> None:
    """The Account column is present and set to 'Accounts Payable'."""
    output = to_quickbooks_csv(_invoice())
    rows = list(csv.DictReader(io.StringIO(output)))
    assert rows[0]["Account"] == "Accounts Payable"
