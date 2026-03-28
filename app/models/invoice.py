"""
Pydantic models for invoice data structures.

ParsedDocument is the output of all document parsers.
ExtractedInvoice / ValidationResult / ConfidenceResult / PipelineResult
form the core pipeline types. Invoice and LineItem are kept for the
Google Sheets integration which expects the richer schema.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ── Parser output ─────────────────────────────────────────────────────────────


class ParsedDocument(BaseModel):
    """
    Normalised output from a document parser.

    All parsers (PDF, CSV, image, text) return this model so the extraction
    pipeline has a single, typed interface regardless of source format.
    """

    text: str = Field(..., description="Extracted plain text, ready for AI extraction")
    content_hash: str = Field(..., description="SHA-256 hex digest of normalised text")
    format: Literal["pdf", "csv", "image", "text"] = Field(
        ..., description="Source document format"
    )
    page_count: int | None = Field(default=None, description="Page count (PDFs only)")
    needs_ocr: bool = Field(
        default=False, description="True if text is absent and OCR processing is needed"
    )
    filename: str = Field(default="", description="Source filename for log context")


# ── Rich invoice model (used by Sheets/Slack integrations) ──────────────────


class LineItem(BaseModel):
    description: str = Field(..., description="Description of the line item")
    quantity: float | None = Field(default=None, description="Units purchased")
    unit_price: float | None = Field(default=None, description="Price per unit")
    total: float = Field(..., description="Line item total")


class Invoice(BaseModel):
    vendor: str = Field(..., description="Vendor or supplier name")
    invoice_number: str = Field(..., description="Unique invoice reference")
    invoice_date: str = Field(..., description="Invoice date as a string")
    currency: str = Field(..., description="Currency code, e.g. GBP, USD")
    total_amount: float = Field(..., gt=0, description="Invoice total amount")
    po_number: str | None = Field(default=None, description="Purchase order number")
    line_items: list[LineItem] = Field(default_factory=list)


# ── Pipeline types ────────────────────────────────────────────────────────────


class ExtractedInvoice(BaseModel):
    """
    Raw output from the AI extraction step.

    All fields are optional — the AI may fail to identify any given field.
    Core fields (vendor, invoice_id, date, amount) are populated by v1 and v2
    prompts; extended fields are populated only by the v2 prompt.
    """

    # ── Core fields (v1 + v2) ─────────────────────────────────────────────
    vendor: str | None = None
    invoice_id: str | None = None
    date: str | None = None
    amount: float | None = None

    # ── Extended fields (v2 only) ─────────────────────────────────────────
    due_date: str | None = None
    currency: str | None = None
    subtotal: float | None = None
    tax: float | None = None
    total: float | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    ai_confidence: dict[str, float] = Field(
        default_factory=dict,
        description="Per-field AI confidence scores from the v2 prompt (0.0–1.0)",
    )


class ValidationResult(BaseModel):
    """Outcome of the business-rule validation step."""

    passed: bool
    errors: list[str] = Field(default_factory=list)


class ConfidenceResult(BaseModel):
    """Composite confidence score for an extracted invoice."""

    score: float = Field(ge=0.0, le=1.0, description="Overall confidence (0–1)")
    completeness: float = Field(ge=0.0, le=1.0, description="Fraction of required fields present")
    validation_score: float = Field(
        ge=0.0, le=1.0, description="1.0 if validation passed, else 0.0"
    )


class PipelineResult(BaseModel):
    """Full result returned by the invoice processing pipeline."""

    status: Literal["processed", "duplicate", "failed"]
    content_hash: str
    extracted: ExtractedInvoice | None = None
    validation: ValidationResult | None = None
    confidence: ConfidenceResult | None = None
    csv_row: list[str] | None = Field(
        default=None,
        description="CSV-ready row: [vendor, invoice_id, date, amount, confidence, validation_passed]",
    )


# ── Legacy response model used by the HTTP route ─────────────────────────────


class ProcessingResult(BaseModel):
    status: str
    vendor: str
    invoice_number: str
    total_amount: float
    currency: str
    approval_required: bool
    issues: list[str]
