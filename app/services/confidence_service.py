"""
Confidence scoring service.

Produces a composite score (0.0–1.0) from three signals:

  - completeness:       fraction of core required fields that are non-None
  - validation_score:   1.0 if validation passed, 0.0 otherwise
  - ai_confidence_avg:  mean of per-field AI confidence scores (v2 prompt only)

Weighting when AI confidence is available:
  score = 0.5 × completeness + 0.3 × validation_score + 0.2 × ai_confidence_avg

Weighting when AI confidence is absent (v1 prompt):
  score = 0.6 × completeness + 0.4 × validation_score
"""

from app.models.invoice import ConfidenceResult, ExtractedInvoice, ValidationResult

_CORE_FIELDS = ("vendor", "invoice_id", "date", "amount")

_WEIGHT_COMPLETENESS_BASE = 0.6
_WEIGHT_VALIDATION_BASE = 0.4

_WEIGHT_COMPLETENESS_WITH_AI = 0.5
_WEIGHT_VALIDATION_WITH_AI = 0.3
_WEIGHT_AI_CONFIDENCE = 0.2


def score_confidence(
    extracted: ExtractedInvoice,
    validation: ValidationResult,
) -> ConfidenceResult:
    """
    Compute a composite confidence score for an extracted invoice.

    Uses AI confidence scores from the v2 prompt when present; falls back to
    the simpler two-signal weighting for v1 prompt results.

    Args:
        extracted: Fields returned by the AI extraction stage.
        validation: Result of the business-rule validation stage.

    Returns:
        ConfidenceResult with individual signal values and composite score.
    """
    present_count = sum(1 for field in _CORE_FIELDS if getattr(extracted, field) is not None)
    completeness = present_count / len(_CORE_FIELDS)
    validation_score = 1.0 if validation.passed else 0.0

    ai_confidence_avg = _mean_ai_confidence(extracted.ai_confidence)

    if ai_confidence_avg is not None:
        composite_score = (
            _WEIGHT_COMPLETENESS_WITH_AI * completeness
            + _WEIGHT_VALIDATION_WITH_AI * validation_score
            + _WEIGHT_AI_CONFIDENCE * ai_confidence_avg
        )
    else:
        composite_score = (
            _WEIGHT_COMPLETENESS_BASE * completeness + _WEIGHT_VALIDATION_BASE * validation_score
        )

    return ConfidenceResult(
        score=round(composite_score, 4),
        completeness=round(completeness, 4),
        validation_score=validation_score,
    )


# ── private helpers ───────────────────────────────────────────────────────────


def _mean_ai_confidence(ai_confidence: dict[str, float]) -> float | None:
    """
    Return the mean of AI confidence scores, or None if the dict is empty.

    Args:
        ai_confidence: Per-field confidence map from the v2 prompt.

    Returns:
        Mean value in [0.0, 1.0], or None if the dict has no entries.
    """
    if not ai_confidence:
        return None
    values = list(ai_confidence.values())
    return sum(values) / len(values)
