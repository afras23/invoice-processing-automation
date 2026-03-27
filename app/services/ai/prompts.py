"""
Versioned prompt templates for invoice extraction.

Each version is a (system_prompt, user_prompt_template) pair. System prompts
contain the extraction instructions; the user prompt template takes the
raw invoice text as its only interpolation argument.

Versions:
    v1 — Extracts the four core fields: vendor, invoice_id, date, amount.
    v2 — Extends v1 with line items and per-field confidence scores.

Usage:
    system_prompt, user_prompt = get_prompt("v1", invoice_text="...")
"""

from __future__ import annotations

_INVOICE_EXTRACTION_V1_SYSTEM = """\
You are an invoice data extraction system.

Extract exactly four fields from the invoice text provided by the user.

Return ONLY valid JSON matching this schema — no markdown, no explanation:

{
  "vendor":     string | null,
  "invoice_id": string | null,
  "date":       string | null,
  "amount":     number | null
}

Field rules:
- vendor:     The supplier or company issuing the invoice.
- invoice_id: The invoice number or reference (e.g. "INV-2026-0042").
- date:       The invoice date in ISO 8601 format (YYYY-MM-DD). Convert if needed.
- amount:     The total amount due as a plain number, no currency symbol.

If a field cannot be determined from the text, use null.
Never invent values not present in the document.
Never include any text outside the JSON object.\
"""

_INVOICE_EXTRACTION_V2_SYSTEM = """\
You are an invoice data extraction system.

Extract the following fields from the invoice text and return a JSON object.
Return ONLY valid JSON — no markdown, no explanation.

Schema:
{
  "vendor":     string | null,
  "invoice_id": string | null,
  "date":       string | null,
  "amount":     number | null,
  "currency":   string | null,
  "line_items": [
    {
      "description": string,
      "quantity":    number | null,
      "unit_price":  number | null,
      "total":       number
    }
  ],
  "confidence": {
    "vendor":     number,
    "invoice_id": number,
    "date":       number,
    "amount":     number
  }
}

Field rules:
- vendor:     The supplier or company issuing the invoice.
- invoice_id: The invoice number or reference (e.g. "INV-2026-0042").
- date:       The invoice date in ISO 8601 format (YYYY-MM-DD). Convert if needed.
- amount:     The total amount due as a plain number, no currency symbol.
- currency:   ISO 4217 currency code (e.g. "USD", "GBP"). Use null if not present.
- line_items: Individual line items if present; empty array if not listed.
- confidence: Per-field certainty score from 0.0 (guessed) to 1.0 (explicit in text).

If a required field cannot be determined from the text, use null.
Never invent values not present in the document.
Never include any text outside the JSON object.\
"""

_USER_PROMPT_TEMPLATE = "INVOICE TEXT:\n{invoice_text}"

_PROMPTS: dict[str, str] = {
    "v1": _INVOICE_EXTRACTION_V1_SYSTEM,
    "v2": _INVOICE_EXTRACTION_V2_SYSTEM,
}

SUPPORTED_VERSIONS: frozenset[str] = frozenset(_PROMPTS.keys())
DEFAULT_VERSION = "v1"


def get_prompt(version: str, *, invoice_text: str) -> tuple[str, str]:
    """
    Return the (system_prompt, user_prompt) pair for the requested version.

    Args:
        version: Prompt version identifier, e.g. "v1" or "v2".
        invoice_text: Raw invoice text to embed in the user prompt.

    Returns:
        A 2-tuple of (system_prompt, user_prompt) strings ready for the API call.

    Raises:
        ValueError: If *version* is not a recognised prompt version.
    """
    if version not in _PROMPTS:
        raise ValueError(
            f"Unknown prompt version '{version}'. Supported versions: {sorted(SUPPORTED_VERSIONS)}"
        )
    system_prompt = _PROMPTS[version]
    user_prompt = _USER_PROMPT_TEMPLATE.format(invoice_text=invoice_text)
    return system_prompt, user_prompt
