"""
Pydantic models for invoice data structures.

ExtractedInvoice / ValidationResult / ConfidenceResult / PipelineResult
form the core pipeline types. Invoice and LineItem are kept for the
Google Sheets integration which expects the richer schema.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ── Rich invoice model (used by Sheets/Slack integrations) ──────────────────

class LineItem(BaseModel):
    description: str = Field(..., description="Description of the line item")
    quantity: Optional[float] = Field(default=None, description="Units purchased")
    unit_price: Optional[float] = Field(default=None, description="Price per unit")
    total: float = Field(..., description="Line item total")


class Invoice(BaseModel):
    vendor: str = Field(..., description="Vendor or supplier name")
    invoice_number: str = Field(..., description="Unique invoice reference")
    invoice_date: str = Field(..., description="Invoice date as a string")
    currency: str = Field(..., description="Currency code, e.g. GBP, USD")
    total_amount: float = Field(..., gt=0, description="Invoice total amount")
    po_number: Optional[str] = Field(default=None, description="Purchase order number")
    line_items: list[LineItem] = Field(default_factory=list)


# ── Pipeline types ────────────────────────────────────────────────────────────

class ExtractedInvoice(BaseModel):
    """Raw output from the AI extraction step. All fields are optional
    because the AI may fail to identify any given field."""

    vendor: Optional[str] = None
    invoice_id: Optional[str] = None
    date: Optional[str] = None
    amount: Optional[float] = None


class ValidationResult(BaseModel):
    """Outcome of the business-rule validation step."""

    passed: bool
    errors: list[str] = Field(default_factory=list)


class ConfidenceResult(BaseModel):
    """Composite confidence score for an extracted invoice."""

    score: float = Field(ge=0.0, le=1.0, description="Overall confidence (0–1)")
    completeness: float = Field(ge=0.0, le=1.0, description="Fraction of required fields present")
    validation_score: float = Field(ge=0.0, le=1.0, description="1.0 if validation passed, else 0.0")


class PipelineResult(BaseModel):
    """Full result returned by the invoice processing pipeline."""

    status: Literal["processed", "duplicate", "failed"]
    content_hash: str
    extracted: Optional[ExtractedInvoice] = None
    validation: Optional[ValidationResult] = None
    confidence: Optional[ConfidenceResult] = None
    csv_row: Optional[list[str]] = Field(
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
