from typing import List
from app.models import Invoice

SEEN_INVOICES = set()

def validate_invoice(invoice: Invoice) -> List[str]:
    issues = []

    key = (invoice.vendor, invoice.invoice_number)
    if key in SEEN_INVOICES:
        issues.append("Duplicate invoice detected")
    else:
        SEEN_INVOICES.add(key)

    if invoice.total_amount <= 0:
        issues.append("Invalid invoice total")

    return issues
