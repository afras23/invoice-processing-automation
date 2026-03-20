"""
Confidence scoring service.

Produces a composite score (0.0–1.0) from two signals:
  - completeness:      fraction of the four required fields that are non-None
  - validation_score:  1.0 if validation passed, 0.0 otherwise

Weighting:  score = 0.6 × completeness + 0.4 × validation_score

Examples
--------
All four fields present, validation passed  → 1.00
All fields present, validation failed       → 0.60
Two of four fields present, valid           → 0.70
Two fields present, validation failed       → 0.30
No fields extracted                         → 0.00
"""

from app.models.invoice import ConfidenceResult, ExtractedInvoice, ValidationResult

_REQUIRED_FIELDS = ("vendor", "invoice_id", "date", "amount")
_COMPLETENESS_WEIGHT = 0.6
_VALIDATION_WEIGHT = 0.4


def score_confidence(
    extracted: ExtractedInvoice,
    validation: ValidationResult,
) -> ConfidenceResult:
    """
    Compute a confidence score for an extracted invoice.

    Args:
        extracted: Fields returned by the extraction stage.
        validation: Result of the validation stage.

    Returns:
        ConfidenceResult with individual signal values and composite score.
    """
    present = sum(
        1 for field in _REQUIRED_FIELDS if getattr(extracted, field) is not None
    )
    completeness = present / len(_REQUIRED_FIELDS)
    validation_score = 1.0 if validation.passed else 0.0

    score = round(
        _COMPLETENESS_WEIGHT * completeness + _VALIDATION_WEIGHT * validation_score,
        4,
    )

    return ConfidenceResult(
        score=score,
        completeness=round(completeness, 4),
        validation_score=validation_score,
    )
