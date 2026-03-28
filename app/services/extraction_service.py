"""
Invoice extraction service.

Orchestrates the full document → structured result pipeline:

  parse → deduplicate → extract (AI) → validate → score → build result

Each stage is a pure function or an injectable dependency, keeping the
pipeline straightforward to test and extend.
"""

from __future__ import annotations

import json
import logging

from app.core.exceptions import ExtractionError, PDFParseError
from app.models.invoice import (
    ConfidenceResult,
    ExtractedInvoice,
    PipelineResult,
    ValidationResult,
)
from app.services.ai.client import AICallResult, AnthropicClient
from app.services.ai.prompts import DEFAULT_VERSION, get_prompt
from app.services.confidence_service import score_confidence
from app.services.deduplication import DeduplicationStore
from app.services.parsing.pdf_parser import parse_document
from app.services.validation_service import validate_extracted

logger = logging.getLogger(__name__)


async def process_invoice(
    content: bytes | str,
    filename: str = "",
    *,
    dedup_store: DeduplicationStore,
    ai_client: AnthropicClient,
    prompt_version: str = DEFAULT_VERSION,
) -> PipelineResult:
    """
    Run the full invoice processing pipeline.

    Args:
        content: Raw bytes (PDF or text) or a pre-decoded string.
        filename: Optional filename for log context.
        dedup_store: Caller-supplied deduplication store (injected so tests
            can use a fresh instance per test).
        ai_client: Injected AI client wrapper (provides retry, cost tracking).
        prompt_version: Prompt template version to use for extraction.

    Returns:
        PipelineResult with status "processed", "duplicate", or "failed".
        On "duplicate" the result contains only status and content_hash.
        On "failed" the result contains status and content_hash only;
        the caller should inspect logs for the root cause.
    """
    # ── 1. Parse ───────────────────────────────────────────────────────────
    try:
        parsed_doc = parse_document(content, filename)
    except PDFParseError as exc:
        logger.error(
            "Document parsing failed",
            extra={"source_file": filename, "error": str(exc)},
        )
        return PipelineResult(status="failed", content_hash="", extracted=None)

    # ── 2. Deduplicate ────────────────────────────────────────────────────
    if dedup_store.check_and_add(parsed_doc.content_hash):
        return PipelineResult(status="duplicate", content_hash=parsed_doc.content_hash)

    # ── 3. Extract ────────────────────────────────────────────────────────
    try:
        extracted_invoice = await extract_invoice_fields(
            parsed_doc.text,
            ai_client=ai_client,
            prompt_version=prompt_version,
        )
    except ExtractionError as exc:
        logger.error(
            "AI extraction failed",
            extra={"source_file": filename, "error": str(exc)},
        )
        return PipelineResult(status="failed", content_hash=parsed_doc.content_hash)

    # ── 4. Validate ───────────────────────────────────────────────────────
    validation_result = validate_extracted(extracted_invoice)

    # ── 5. Score ──────────────────────────────────────────────────────────
    confidence_result = score_confidence(extracted_invoice, validation_result)

    logger.info(
        "Pipeline complete",
        extra={
            "source_file": filename,
            "confidence": confidence_result.score,
            "validation_passed": validation_result.passed,
            "hash": parsed_doc.content_hash[:16],
            "prompt_version": prompt_version,
            "needs_ocr": parsed_doc.needs_ocr,
        },
    )

    # ── 6. Build result ───────────────────────────────────────────────────
    return PipelineResult(
        status="processed",
        content_hash=parsed_doc.content_hash,
        extracted=extracted_invoice,
        validation=validation_result,
        confidence=confidence_result,
        csv_row=_build_csv_row(extracted_invoice, confidence_result, validation_result),
    )


async def extract_invoice_fields(
    raw_text: str,
    *,
    ai_client: AnthropicClient,
    prompt_version: str = DEFAULT_VERSION,
) -> ExtractedInvoice:
    """
    Extract core invoice fields from raw text using the AI client.

    Args:
        raw_text: Plain text of the invoice document.
        ai_client: Injected AI client (handles retry, cost, circuit breaker).
        prompt_version: Prompt template version to use ("v1" or "v2").

    Returns:
        ExtractedInvoice where missing fields are None — the validation and
        confidence stages are responsible for handling gaps.

    Raises:
        ExtractionError: If the AI call fails or returns unparseable output.
    """
    system_prompt, user_message = get_prompt(prompt_version, invoice_text=raw_text)

    ai_call_result: AICallResult = await ai_client.complete(
        system_prompt,
        user_message,
        prompt_version=prompt_version,
    )

    try:
        parsed_data = json.loads(ai_call_result.content)
    except json.JSONDecodeError as exc:
        logger.error(
            "AI response was not valid JSON",
            extra={"response_preview": ai_call_result.content[:300]},
        )
        raise ExtractionError(
            "AI returned invalid JSON",
            context={"response_preview": ai_call_result.content[:200]},
        ) from exc

    logger.info(
        "Extraction complete",
        extra={
            "input_tokens": ai_call_result.input_tokens,
            "output_tokens": ai_call_result.output_tokens,
            "cost_usd": ai_call_result.cost_usd,
            "latency_ms": ai_call_result.latency_ms,
            "prompt_version": prompt_version,
        },
    )

    return ExtractedInvoice.model_validate(parsed_data)


def _build_csv_row(
    extracted: ExtractedInvoice,
    confidence: ConfidenceResult,
    validation: ValidationResult,
) -> list[str]:
    """Build a 7-column CSV row from pipeline stage outputs."""
    total = extracted.total or extracted.amount
    return [
        extracted.vendor or "",
        extracted.invoice_id or "",
        extracted.date or "",
        str(total) if total is not None else "",
        extracted.currency or "",
        str(confidence.score),
        "YES" if validation.passed else "NO",
    ]
