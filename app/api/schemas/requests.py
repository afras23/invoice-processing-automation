"""
Pydantic request models for the invoice API.

FastAPI uses these at the route boundary: invalid requests are rejected
before any service code runs, and the OpenAPI docs are auto-generated
from the field descriptions and constraints.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class ProcessInvoiceRequest(BaseModel):
    """
    Request body for the JSON-based invoice processing endpoint.

    Used when the client posts pre-extracted text rather than uploading a file.
    """

    invoice_text: str = Field(
        ...,
        min_length=1,
        max_length=100_000,
        description="Raw plain-text content of the invoice to process.",
    )
    prompt_version: str = Field(
        default="v1",
        description="Prompt template version to use for AI extraction ('v1' or 'v2').",
    )
    filename: str = Field(
        default="",
        description="Optional source filename for log context.",
    )

    @model_validator(mode="after")
    def strip_invoice_text(self) -> ProcessInvoiceRequest:
        """Strip surrounding whitespace from invoice_text."""
        self.invoice_text = self.invoice_text.strip()
        return self
