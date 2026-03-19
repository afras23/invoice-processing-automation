"""
Pydantic models for invoice data structures.
"""

from typing import Optional

from pydantic import BaseModel, Field


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


class ProcessingResult(BaseModel):
    status: str
    vendor: str
    invoice_number: str
    total_amount: float
    currency: str
    approval_required: bool
    issues: list[str]
