"""
Invoice extraction service.

Two entry points:
  extract_invoice_fields(raw_text) → ExtractedInvoice   [pipeline path]
  extract_text_from_pdf(path)      → str                [legacy / ingestion helper]
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import anthropic
import pdfplumber

from app.config import settings
from app.core.exceptions import ExtractionError, PDFParseError
from app.models.invoice import ExtractedInvoice

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_REQUIRED_FIELDS = {"vendor", "invoice_id", "date", "amount"}


def extract_text_from_pdf(path: str) -> str:
    """
    Extract raw text from a PDF file path.

    Raises:
        PDFParseError: If the file cannot be opened or parsed.
    """
    try:
        with pdfplumber.open(path) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return "\n".join(pages)
    except Exception as e:
        raise PDFParseError(f"Failed to parse PDF at {path}") from e


def extract_invoice_fields(
    raw_text: str,
    *,
    client: anthropic.Anthropic | None = None,
) -> ExtractedInvoice:
    """
    Extract the four core invoice fields from raw text using the Claude API.

    Returns an ExtractedInvoice where missing fields are None — the caller
    (validation + confidence stages) is responsible for handling gaps.

    Args:
        raw_text: Plain text of the invoice document.
        client: Optional pre-built Anthropic client (injected in tests).

    Raises:
        ExtractionError: If the API call fails or returns unparseable output.
    """
    prompt_path = _PROMPTS_DIR / "invoice_extraction.txt"
    try:
        system_prompt = prompt_path.read_text()
    except FileNotFoundError as e:
        raise ExtractionError(f"Prompt file not found: {prompt_path}") from e

    if client is None:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    logger.info("Sending invoice to AI for extraction", extra={"model": settings.ai_model})

    try:
        message = client.messages.create(
            model=settings.ai_model,
            max_tokens=512,
            system=system_prompt,
            messages=[{"role": "user", "content": f"INVOICE TEXT:\n{raw_text}"}],
        )
    except anthropic.APIError as e:
        raise ExtractionError(f"AI API call failed: {e}") from e

    raw_response = message.content[0].text

    try:
        data = json.loads(raw_response)
    except json.JSONDecodeError as e:
        logger.error(
            "AI response was not valid JSON",
            extra={"response_preview": raw_response[:300]},
        )
        raise ExtractionError("AI returned invalid JSON") from e

    logger.info(
        "Extraction complete",
        extra={
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
            "fields_present": [f for f in _REQUIRED_FIELDS if data.get(f) is not None],
        },
    )

    # Build the model; unknown keys are silently dropped via model_validate
    return ExtractedInvoice.model_validate(data)
