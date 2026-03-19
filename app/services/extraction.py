"""
Invoice extraction service.

Handles PDF text extraction and AI-powered structured data extraction.
"""

import json
import logging
from pathlib import Path

import anthropic
import pdfplumber

from app.config import settings
from app.core.exceptions import ExtractionError, PDFParseError

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def extract_text_from_pdf(path: str) -> str:
    """
    Extract raw text from a PDF file.

    Args:
        path: Filesystem path to the PDF.

    Returns:
        Concatenated text from all pages.

    Raises:
        PDFParseError: If the file cannot be opened or parsed.
    """
    try:
        with pdfplumber.open(path) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return "\n".join(pages)
    except Exception as e:
        raise PDFParseError(f"Failed to parse PDF at {path}") from e


def extract_invoice_data(pdf_path: str) -> dict:
    """
    Extract structured invoice data from a PDF using the Claude API.

    Args:
        pdf_path: Filesystem path to the PDF invoice.

    Returns:
        Dictionary matching the Invoice schema.

    Raises:
        PDFParseError: If the PDF cannot be read.
        ExtractionError: If the AI response cannot be parsed.
    """
    raw_text = extract_text_from_pdf(pdf_path)

    prompt_path = _PROMPTS_DIR / "invoice_extraction.txt"
    try:
        system_prompt = prompt_path.read_text()
    except FileNotFoundError as e:
        raise ExtractionError(f"Prompt file not found: {prompt_path}") from e

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    logger.info("Sending invoice to AI for extraction", extra={"model": settings.ai_model})

    try:
        message = client.messages.create(
            model=settings.ai_model,
            max_tokens=1024,
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
        },
    )

    return data
