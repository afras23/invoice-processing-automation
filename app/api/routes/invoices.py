"""
Invoice upload and processing routes.

Mounted at /api/v1/invoices:
  POST /api/v1/invoices/upload — accept a file upload and run the pipeline
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.core.exceptions import IntegrationError
from app.dependencies import get_ai_client, get_dedup_store
from app.integrations.sheets import write_to_sheet
from app.integrations.slack import send_slack_notification
from app.models.invoice import Invoice, PipelineResult
from app.services.ai.client import AnthropicClient
from app.services.deduplication import DeduplicationStore
from app.services.extraction_service import process_invoice
from app.services.validation_service import requires_approval

router = APIRouter(tags=["invoices"])
logger = logging.getLogger(__name__)

_MIN_CONFIDENCE_FOR_INTEGRATIONS = 0.6


@router.post("/upload", response_model=PipelineResult)
async def upload_invoice(
    file: UploadFile,
    ai_client: AnthropicClient = Depends(get_ai_client),
    dedup_store: DeduplicationStore = Depends(get_dedup_store),
) -> PipelineResult:
    """
    Process an uploaded invoice document through the full pipeline.

    Accepts PDF or plain-text files. Returns a PipelineResult with extraction,
    validation, and confidence data. Duplicate submissions return status="duplicate"
    with HTTP 200.

    Args:
        file: Uploaded invoice file (PDF or plain text).
        ai_client: Injected AI client with retry and cost tracking.
        dedup_store: Injected deduplication store for this request scope.

    Returns:
        PipelineResult with status "processed" or "duplicate".

    Raises:
        HTTPException 400: If filename or file content is missing.
        HTTPException 422: If the invoice could not be processed.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    invoice_bytes = await file.read()
    if not invoice_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    pipeline_result = await process_invoice(
        invoice_bytes,
        filename=file.filename,
        dedup_store=dedup_store,
        ai_client=ai_client,
    )

    if pipeline_result.status == "failed":
        raise HTTPException(status_code=422, detail="Invoice could not be processed")

    if _should_run_integrations(pipeline_result):
        _run_integrations(pipeline_result)

    return pipeline_result


# ── private helpers ───────────────────────────────────────────────────────────


def _should_run_integrations(pipeline_result: PipelineResult) -> bool:
    return (
        pipeline_result.status == "processed"
        and pipeline_result.confidence is not None
        and pipeline_result.confidence.score >= _MIN_CONFIDENCE_FOR_INTEGRATIONS
        and pipeline_result.extracted is not None
    )


def _run_integrations(pipeline_result: PipelineResult) -> None:
    """Fire Sheets and Slack as best-effort side effects; never raise."""
    extracted = pipeline_result.extracted
    if extracted is None:
        return

    approval_required = requires_approval(extracted.amount or 0.0)

    try:
        minimal_invoice = Invoice(
            vendor=extracted.vendor or "Unknown",
            invoice_number=extracted.invoice_id or "N/A",
            invoice_date=extracted.date or "",
            currency="",
            total_amount=extracted.amount or 0.0,
            line_items=[],
        )
        write_to_sheet(minimal_invoice, approval_required)
    except IntegrationError as exc:
        logger.warning(
            "Sheets write failed, continuing",
            extra={"error": str(exc)},
        )

    try:
        confidence_score = pipeline_result.confidence.score if pipeline_result.confidence else 0.0
        send_slack_notification(
            f"Invoice processed: {extracted.vendor} | "
            f"{extracted.amount} | "
            f"Confidence: {confidence_score:.0%} | "
            f"Approval: {'required' if approval_required else 'not required'}"
        )
    except IntegrationError as exc:
        logger.warning(
            "Slack notification failed, continuing",
            extra={"error": str(exc)},
        )
