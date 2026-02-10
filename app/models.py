from pydantic import BaseModel
from typing import List, Optional

class LineItem(BaseModel):
    description: str
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    total: float

class Invoice(BaseModel):
    vendor: str
    invoice_number: str
    invoice_date: str
    currency: str
    total_amount: float
    po_number: Optional[str] = None
    line_items: List[LineItem]
