"""
Invoice upload route.

Accepts a PDF upload and runs it through the full processing pipeline.
"""

import logging
import os
import shutil
import tempfile

from fastapi import APIRouter, HTTPException, UploadFile

from app.core.exceptions import ExtractionError, IntegrationError, PDFParseError
from app.integrations.sheets import write_to_sheet
from app.integrations.slack import send_slack_notification
from app.models.invoice import Invoice, ProcessingResult
from app.services.extraction import extract_invoice_data
from app.services.validation import requires_approval, validate_invoice

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/upload-invoice", response_model=ProcessingResult)
async def upload_invoice(file: UploadFile) -> ProcessingResult:
    """
    Process an uploaded PDF invoice.

    Extracts structured data via AI, validates it, determines approval
    status, writes to Google Sheets, and sends a Slack notification.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        try:
            data = extract_invoice_data(tmp_path)
        except (PDFParseError, ExtractionError) as e:
            logger.error("Invoice extraction failed", extra={"error": str(e)})
            raise HTTPException(status_code=422, detail=str(e))

        try:
            invoice = Invoice(**data)
        except Exception as e:
            logger.error("Extracted data failed schema validation", extra={"error": str(e)})
            raise HTTPException(status_code=422, detail=f"Extraction produced invalid data: {e}")

        issues = validate_invoice(invoice)
        approval = requires_approval(invoice.total_amount)

        try:
            write_to_sheet(invoice, approval)
        except IntegrationError as e:
            logger.warning("Sheets write failed, continuing", extra={"error": str(e)})

        try:
            send_slack_notification(
                f"Invoice processed: {invoice.vendor} | "
                f"{invoice.currency}{invoice.total_amount} | "
                f"Approval: {'required' if approval else 'not required'}"
            )
        except IntegrationError as e:
            logger.warning("Slack notification failed, continuing", extra={"error": str(e)})

        logger.info(
            "Invoice processing complete",
            extra={
                "vendor": invoice.vendor,
                "invoice_number": invoice.invoice_number,
                "total_amount": invoice.total_amount,
                "approval_required": approval,
                "issues_count": len(issues),
            },
        )

        return ProcessingResult(
            status="processed",
            vendor=invoice.vendor,
            invoice_number=invoice.invoice_number,
            total_amount=invoice.total_amount,
            currency=invoice.currency,
            approval_required=approval,
            issues=issues,
        )
    finally:
        os.unlink(tmp_path)
