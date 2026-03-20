"""
Tests for the validation service.
"""

from app.models.invoice import ExtractedInvoice, Invoice, LineItem
from app.services.validation import requires_approval, validate_extracted, validate_invoice


# ── validate_extracted (pipeline validator) ───────────────────────────────────

def _extracted(**kwargs) -> ExtractedInvoice:
    defaults = dict(vendor="Acme Corp", invoice_id="INV-001", date="2026-03-01", amount=100.0)
    defaults.update(kwargs)
    return ExtractedInvoice(**defaults)


def test_fully_populated_invoice_passes():
    result = validate_extracted(_extracted())
    assert result.passed is True
    assert result.errors == []


def test_missing_vendor_fails():
    result = validate_extracted(_extracted(vendor=None))
    assert result.passed is False
    assert any("vendor" in e for e in result.errors)


def test_missing_invoice_id_fails():
    result = validate_extracted(_extracted(invoice_id=None))
    assert result.passed is False
    assert any("invoice_id" in e for e in result.errors)


def test_missing_date_fails():
    result = validate_extracted(_extracted(date=None))
    assert result.passed is False
    assert any("date" in e for e in result.errors)


def test_missing_amount_fails():
    result = validate_extracted(_extracted(amount=None))
    assert result.passed is False
    assert any("amount" in e for e in result.errors)


def test_zero_amount_fails():
    result = validate_extracted(_extracted(amount=0.0))
    assert result.passed is False
    assert any("amount" in e for e in result.errors)


def test_negative_amount_fails():
    result = validate_extracted(_extracted(amount=-50.0))
    assert result.passed is False


def test_invalid_date_format_fails():
    result = validate_extracted(_extracted(date="not-a-date"))
    assert result.passed is False
    assert any("date" in e for e in result.errors)


def test_iso_date_is_accepted():
    assert validate_extracted(_extracted(date="2026-12-31")).passed is True


def test_slash_date_is_accepted():
    assert validate_extracted(_extracted(date="31/12/2026")).passed is True


def test_multiple_missing_fields_all_reported():
    result = validate_extracted(ExtractedInvoice())
    assert len(result.errors) == 4


# ── requires_approval ─────────────────────────────────────────────────────────

def test_requires_approval_above_threshold(monkeypatch):
    monkeypatch.setattr("app.services.validation.settings.approval_threshold", 500.0)
    assert requires_approval(501.0) is True


def test_does_not_require_approval_below_threshold(monkeypatch):
    monkeypatch.setattr("app.services.validation.settings.approval_threshold", 500.0)
    assert requires_approval(499.99) is False


def test_requires_approval_at_exact_threshold(monkeypatch):
    monkeypatch.setattr("app.services.validation.settings.approval_threshold", 500.0)
    assert requires_approval(500.0) is False


# ── validate_invoice (legacy, used by HTTP route) ─────────────────────────────

def _make_invoice(**overrides) -> Invoice:
    defaults = dict(
        vendor="Acme Corp",
        invoice_number="INV-001",
        invoice_date="2026-03-01",
        currency="GBP",
        total_amount=100.0,
        line_items=[LineItem(description="Widget", total=100.0)],
    )
    defaults.update(overrides)
    return Invoice(**defaults)


def test_valid_legacy_invoice_has_no_issues():
    assert validate_invoice(_make_invoice()) == []


def test_legacy_invoice_with_no_line_items_reports_issue():
    issues = validate_invoice(_make_invoice(line_items=[]))
    assert any("line item" in i.lower() for i in issues)
