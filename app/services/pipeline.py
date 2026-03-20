"""
Invoice processing pipeline.

Orchestrates the full document → output flow:

  ingest → deduplicate → extract → validate → score → build result

Each stage is a pure function or an injectable dependency, making the
pipeline straightforward to test in isolation.
"""

from __future__ import annotations

import logging

import anthropic

from app.core.exceptions import ExtractionError, PDFParseError
from app.models.invoice import (
    ConfidenceResult,
    ExtractedInvoice,
    PipelineResult,
    ValidationResult,
)
from app.services.confidence import score_confidence
from app.services.deduplication import DeduplicationStore, compute_hash
from app.services.extraction import extract_invoice_fields
from app.services.ingestion import ingest
from app.services.validation import validate_extracted

logger = logging.getLogger(__name__)


def process_invoice(
    content: bytes | str,
    filename: str = "",
    *,
    dedup_store: DeduplicationStore,
    ai_client: anthropic.Anthropic | None = None,
) -> PipelineResult:
    """
    Run the full invoice processing pipeline.

    Args:
        content:      Raw bytes (PDF or text) or a pre-decoded string.
        filename:     Optional filename for log context.
        dedup_store:  Caller-supplied deduplication store (injected so that
                      tests can use a fresh instance per test).
        ai_client:    Optional Anthropic client; created from settings if None.

    Returns:
        PipelineResult with status "processed", "duplicate", or "failed".
        On "duplicate" the result contains only status and content_hash.
        On "failed" the result contains status, content_hash, and no other
        fields (the caller should inspect logs for the root cause).
    """
    # ── 1. Ingest ─────────────────────────────────────────────────────────
    try:
        raw_text = ingest(content, filename)
    except PDFParseError as e:
        logger.error("Ingestion failed", extra={"source_file": filename, "error": str(e)})
        return PipelineResult(status="failed", content_hash="", extracted=None)

    content_hash = compute_hash(raw_text)

    # ── 2. Deduplicate ────────────────────────────────────────────────────
    if dedup_store.check_and_add(content_hash):
        return PipelineResult(status="duplicate", content_hash=content_hash)

    # ── 3. Extract ────────────────────────────────────────────────────────
    try:
        extracted = extract_invoice_fields(raw_text, client=ai_client)
    except ExtractionError as e:
        logger.error("Extraction failed", extra={"source_file": filename, "error": str(e)})
        # Still record the hash so a retry with the same file is not re-extracted
        return PipelineResult(status="failed", content_hash=content_hash)

    # ── 4. Validate ───────────────────────────────────────────────────────
    validation = validate_extracted(extracted)

    # ── 5. Score ──────────────────────────────────────────────────────────
    confidence = score_confidence(extracted, validation)

    logger.info(
        "Pipeline complete",
        extra={
            "source_file": filename,
            "confidence": confidence.score,
            "validation_passed": validation.passed,
            "hash": content_hash[:16],
        },
    )

    # ── 6. Build result ───────────────────────────────────────────────────
    return PipelineResult(
        status="processed",
        content_hash=content_hash,
        extracted=extracted,
        validation=validation,
        confidence=confidence,
        csv_row=_build_csv_row(extracted, confidence, validation),
    )


def _build_csv_row(
    extracted: ExtractedInvoice,
    confidence: ConfidenceResult,
    validation: ValidationResult,
) -> list[str]:
    return [
        extracted.vendor or "",
        extracted.invoice_id or "",
        extracted.date or "",
        str(extracted.amount) if extracted.amount is not None else "",
        str(confidence.score),
        "YES" if validation.passed else "NO",
    ]
