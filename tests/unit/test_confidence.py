"""
Unit tests for the confidence scoring service.
"""

from __future__ import annotations

from app.models.invoice import ExtractedInvoice, ValidationResult
from app.services.confidence_service import score_confidence


def _valid() -> ValidationResult:
    return ValidationResult(passed=True)


def _failed(errors: list[str] | None = None) -> ValidationResult:
    return ValidationResult(passed=False, errors=errors or ["amount is missing"])


def _approx(expected: float, rel: float = 1e-4) -> _Approx:
    return _Approx(expected, rel)


class _Approx:
    def __init__(self, expected: float, rel: float) -> None:
        self.expected = expected
        self.rel = rel

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, int | float):
            return NotImplemented
        return abs(other - self.expected) <= self.rel * max(abs(self.expected), 1e-12)

    def __repr__(self) -> str:
        return f"≈{self.expected}"


def test_all_fields_present_and_valid_scores_1():
    extracted = ExtractedInvoice(vendor="Acme", invoice_id="INV-1", date="2026-03-01", amount=100.0)
    result = score_confidence(extracted, _valid())
    assert result.score == 1.0
    assert result.completeness == 1.0
    assert result.validation_score == 1.0


def test_no_fields_present_scores_0():
    extracted = ExtractedInvoice()
    result = score_confidence(extracted, _failed())
    assert result.score == 0.0
    assert result.completeness == 0.0
    assert result.validation_score == 0.0


def test_all_fields_present_but_validation_failed():
    extracted = ExtractedInvoice(vendor="Acme", invoice_id="INV-1", date="2026-03-01", amount=-1.0)
    result = score_confidence(extracted, _failed(["amount must be greater than zero"]))
    assert result.completeness == 1.0
    assert result.validation_score == 0.0
    assert result.score == _approx(0.6)


def test_half_fields_present_and_valid():
    extracted = ExtractedInvoice(vendor="Acme", invoice_id="INV-1")
    result = score_confidence(extracted, _valid())
    assert result.completeness == 0.5
    assert result.validation_score == 1.0
    assert result.score == _approx(0.7)


def test_score_is_between_0_and_1_for_all_combinations():
    cases = [
        ExtractedInvoice(),
        ExtractedInvoice(vendor="X"),
        ExtractedInvoice(vendor="X", invoice_id="Y"),
        ExtractedInvoice(vendor="X", invoice_id="Y", date="2026-01-01"),
        ExtractedInvoice(vendor="X", invoice_id="Y", date="2026-01-01", amount=1.0),
    ]
    for extracted in cases:
        for validation in [_valid(), _failed()]:
            result = score_confidence(extracted, validation)
            assert 0.0 <= result.score <= 1.0
