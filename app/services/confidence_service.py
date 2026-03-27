"""
Confidence scoring service.

Produces a composite score (0.0–1.0) from two signals:
  - completeness:      fraction of the four required fields that are non-None
  - validation_score:  1.0 if validation passed, 0.0 otherwise

Weighting:  score = 0.6 × completeness + 0.4 × validation_score
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
    Compute a composite confidence score for an extracted invoice.

    Args:
        extracted: Fields returned by the AI extraction stage.
        validation: Result of the business-rule validation stage.

    Returns:
        ConfidenceResult with individual signal values and composite score.
    """
    present_count = sum(1 for field in _REQUIRED_FIELDS if getattr(extracted, field) is not None)
    completeness = present_count / len(_REQUIRED_FIELDS)
    validation_score = 1.0 if validation.passed else 0.0

    composite_score = round(
        _COMPLETENESS_WEIGHT * completeness + _VALIDATION_WEIGHT * validation_score,
        4,
    )

    return ConfidenceResult(
        score=composite_score,
        completeness=round(completeness, 4),
        validation_score=validation_score,
    )
