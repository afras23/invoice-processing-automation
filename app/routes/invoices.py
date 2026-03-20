"""
Invoice upload route.

Accepts a PDF (or plain-text) upload and runs it through the processing
pipeline.  Google Sheets and Slack notifications fire as optional
post-processing when the pipeline returns a high-confidence result.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, UploadFile

from app.core.exceptions import IntegrationError
from app.integrations.sheets import write_to_sheet
from app.integrations.slack import send_slack_notification
from app.models.invoice import Invoice, PipelineResult
from app.services.deduplication import get_store
from app.services.pipeline import process_invoice
from app.services.validation import requires_approval

router = APIRouter()
logger = logging.getLogger(__name__)

_MIN_CONFIDENCE_FOR_INTEGRATIONS = 0.6


@router.post("/upload-invoice", response_model=PipelineResult)
async def upload_invoice(file: UploadFile) -> PipelineResult:
    """
    Process an uploaded invoice document.

    Accepts PDF or plain-text files.  Returns a PipelineResult with
    extraction, validation, and confidence data.  On duplicate submission
    returns status="duplicate" with HTTP 200.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    result = process_invoice(
        content,
        filename=file.filename,
        dedup_store=get_store(),
    )

    if result.status == "failed":
        raise HTTPException(status_code=422, detail="Invoice could not be processed")

    # ── Optional integrations ─────────────────────────────────────────────
    if (
        result.status == "processed"
        and result.confidence
        and result.confidence.score >= _MIN_CONFIDENCE_FOR_INTEGRATIONS
        and result.extracted
    ):
        _run_integrations(result)

    return result


# ── private helpers ───────────────────────────────────────────────────────────

def _run_integrations(result: PipelineResult) -> None:
    """Fire Sheets and Slack as best-effort side effects."""
    ext = result.extracted
    if ext is None:
        return

    approval = requires_approval(ext.amount or 0.0)

    # Build a minimal Invoice for the Sheets integration
    try:
        invoice = Invoice(
            vendor=ext.vendor or "Unknown",
            invoice_number=ext.invoice_id or "N/A",
            invoice_date=ext.date or "",
            currency="",
            total_amount=ext.amount or 0.0,
            line_items=[],
        )
        write_to_sheet(invoice, approval)
    except (IntegrationError, Exception) as e:
        logger.warning("Sheets write failed, continuing", extra={"error": str(e)})

    try:
        send_slack_notification(
            f"Invoice processed: {ext.vendor} | "
            f"{ext.amount} | "
            f"Confidence: {result.confidence.score:.0%} | "  # type: ignore[union-attr]
            f"Approval: {'required' if approval else 'not required'}"
        )
    except (IntegrationError, Exception) as e:
        logger.warning("Slack notification failed, continuing", extra={"error": str(e)})
