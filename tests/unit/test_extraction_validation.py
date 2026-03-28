"""
Unit tests for extraction, validation, and confidence services.

Covers:
- ExtractedInvoice with full v2 fields
- Missing fields validate as null (not error at extraction stage)
- Cross-field total validation: sum(line_items) + tax == total
- Duplicate detection via content hash
- Currency normalisation (USD / GBP / EUR and aliases)
- Line items sum matches total passes validation
- Line items sum mismatch fails validation
- Parameterised currency normalization
- Confidence scoring with and without AI confidence scores
"""

from __future__ import annotations

import pytest

from app.models.invoice import ConfidenceResult, ExtractedInvoice, LineItem, ValidationResult
from app.services.confidence_service import score_confidence
from app.services.deduplication import DeduplicationStore, compute_hash
from app.services.validation_service import (
    normalise_currency,
    validate_extracted,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_complete_invoice(**overrides: object) -> ExtractedInvoice:
    defaults = {
        "vendor": "Acme Corp",
        "invoice_id": "INV-001",
        "date": "2026-03-01",
        "amount": 1500.0,
    }
    defaults.update(overrides)
    return ExtractedInvoice(**defaults)


def _make_line_items(totals: list[float]) -> list[LineItem]:
    return [LineItem(description=f"Item {i + 1}", total=total) for i, total in enumerate(totals)]


# ── ExtractedInvoice model ────────────────────────────────────────────────────


def test_extracted_invoice_all_fields_optional():
    extracted = ExtractedInvoice()
    assert extracted.vendor is None
    assert extracted.invoice_id is None
    assert extracted.date is None
    assert extracted.amount is None
    assert extracted.due_date is None
    assert extracted.currency is None
    assert extracted.subtotal is None
    assert extracted.tax is None
    assert extracted.total is None
    assert extracted.line_items == []
    assert extracted.ai_confidence == {}


def test_extracted_invoice_v2_fields_populated():
    line_items = _make_line_items([100.0, 200.0])
    extracted = ExtractedInvoice(
        vendor="Beta Ltd",
        invoice_id="INV-999",
        date="2026-01-15",
        amount=330.0,
        due_date="2026-02-15",
        currency="GBP",
        subtotal=300.0,
        tax=30.0,
        total=330.0,
        line_items=line_items,
        ai_confidence={"vendor": 0.95, "invoice_id": 0.9, "date": 0.8, "amount": 0.85},
    )
    assert extracted.currency == "GBP"
    assert extracted.subtotal == 300.0
    assert extracted.tax == 30.0
    assert extracted.total == 330.0
    assert len(extracted.line_items) == 2


# ── Validation: required fields ───────────────────────────────────────────────


def test_complete_invoice_passes_validation():
    result = validate_extracted(_make_complete_invoice())
    assert result.passed is True
    assert result.errors == []


def test_missing_vendor_fails_validation():
    result = validate_extracted(_make_complete_invoice(vendor=None))
    assert result.passed is False
    assert any("vendor" in e for e in result.errors)


def test_missing_invoice_id_fails_validation():
    result = validate_extracted(_make_complete_invoice(invoice_id=None))
    assert result.passed is False
    assert any("invoice_id" in e for e in result.errors)


def test_missing_date_fails_validation():
    result = validate_extracted(_make_complete_invoice(date=None))
    assert result.passed is False
    assert any("date" in e for e in result.errors)


def test_zero_amount_fails_validation():
    result = validate_extracted(_make_complete_invoice(amount=0.0))
    assert result.passed is False
    assert any("greater than zero" in e for e in result.errors)


def test_negative_amount_fails_validation():
    result = validate_extracted(_make_complete_invoice(amount=-50.0))
    assert result.passed is False


# ── Validation: cross-field totals ────────────────────────────────────────────


def test_line_items_sum_matches_total_passes():
    line_items = _make_line_items([100.0, 200.0, 300.0])
    extracted = _make_complete_invoice(
        line_items=line_items,
        tax=0.0,
        total=600.0,
        amount=600.0,
    )
    result = validate_extracted(extracted)
    assert result.passed is True
    assert not any("does not match" in e for e in result.errors)


def test_line_items_sum_with_tax_matches_total_passes():
    line_items = _make_line_items([500.0, 250.0])
    extracted = _make_complete_invoice(
        line_items=line_items,
        tax=75.0,
        total=825.0,
        amount=825.0,
    )
    result = validate_extracted(extracted)
    assert not any("does not match" in e for e in result.errors)


def test_line_items_sum_mismatch_fails_validation():
    line_items = _make_line_items([100.0, 200.0])
    extracted = _make_complete_invoice(
        line_items=line_items,
        tax=0.0,
        total=999.0,  # Wrong: should be 300.0
        amount=999.0,
    )
    result = validate_extracted(extracted)
    assert result.passed is False
    assert any("does not match" in e for e in result.errors)


def test_cross_field_skipped_when_no_line_items():
    extracted = _make_complete_invoice(total=1500.0)
    result = validate_extracted(extracted)
    # No line items → cross-field check not applicable
    assert not any("does not match" in e for e in result.errors)


def test_due_date_before_invoice_date_fails():
    extracted = _make_complete_invoice(date="2026-03-15", due_date="2026-03-01")
    result = validate_extracted(extracted)
    assert result.passed is False
    assert any("before invoice date" in e for e in result.errors)


def test_valid_due_date_passes():
    extracted = _make_complete_invoice(date="2026-03-01", due_date="2026-03-31")
    result = validate_extracted(extracted)
    assert not any("before invoice date" in e for e in result.errors)


# ── Currency normalisation ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("USD", "USD"),
        ("usd", "USD"),
        ("$", "USD"),
        ("GBP", "GBP"),
        ("gbp", "GBP"),
        ("£", "GBP"),
        ("EUR", "EUR"),
        ("€", "EUR"),
        ("euro", "EUR"),
        ("pound", "GBP"),
        ("us dollar", "USD"),
        ("CAD", "CAD"),  # Unknown → uppercase passthrough
        (None, None),
    ],
)
def test_normalise_currency(raw: str | None, expected: str | None):
    assert normalise_currency(raw) == expected


def test_validate_extracted_normalises_currency_in_place():
    extracted = _make_complete_invoice(currency="$")
    validate_extracted(extracted)
    assert extracted.currency == "USD"


# ── Duplicate detection ───────────────────────────────────────────────────────


def test_duplicate_detected_by_content_hash():
    store = DeduplicationStore()
    text = "Invoice from Acme Corp, total 1500"
    content_hash = compute_hash(text)

    store.check_and_add(content_hash)
    assert store.check_and_add(content_hash) is True


def test_different_text_not_duplicate():
    store = DeduplicationStore()
    hash_a = compute_hash("Invoice A")
    hash_b = compute_hash("Invoice B")

    store.check_and_add(hash_a)
    assert store.check_and_add(hash_b) is False


# ── Confidence scoring ────────────────────────────────────────────────────────


def test_confidence_full_invoice_high_score():
    extracted = _make_complete_invoice()
    validation = ValidationResult(passed=True, errors=[])
    result = score_confidence(extracted, validation)
    assert result.score == pytest.approx(1.0)
    assert result.completeness == 1.0
    assert result.validation_score == 1.0


def test_confidence_partial_invoice_lower_score():
    extracted = ExtractedInvoice(vendor="Acme Corp", amount=100.0)
    validation = ValidationResult(passed=False, errors=["invoice_id is missing", "date is missing"])
    result = score_confidence(extracted, validation)
    assert result.score < 0.7
    assert result.completeness == 0.5


def test_confidence_with_ai_scores_uses_three_signals():
    extracted = _make_complete_invoice(
        ai_confidence={"vendor": 0.9, "invoice_id": 0.8, "date": 0.95, "amount": 0.85}
    )
    validation = ValidationResult(passed=True, errors=[])
    result = score_confidence(extracted, validation)
    # With AI confidence: 0.5*1.0 + 0.3*1.0 + 0.2*mean(0.9,0.8,0.95,0.85) = 0.5+0.3+0.2*0.875
    expected = 0.5 + 0.3 + 0.2 * 0.875
    assert result.score == pytest.approx(expected, abs=0.001)


def test_confidence_returns_confidence_result_model():
    extracted = _make_complete_invoice()
    validation = ValidationResult(passed=True, errors=[])
    result = score_confidence(extracted, validation)
    assert isinstance(result, ConfidenceResult)
    assert 0.0 <= result.score <= 1.0
