import gspread
from oauth2client.service_account import ServiceAccountCredentials
from app.models import Invoice

def write_to_sheet(invoice: Invoice, approval_required: bool):
    scope = ["https://spreadsheets.google.com/feeds",
             "https://www.googleapis.com/auth/drive"]

    creds = ServiceAccountCredentials.from_json_keyfile_name(
        "service_account.json", scope
    )

    client = gspread.authorize(creds)
    sheet = client.open("Invoices").sheet1

    sheet.append_row([
        invoice.vendor,
        invoice.invoice_number,
        invoice.invoice_date,
        invoice.currency,
        invoice.total_amount,
        invoice.po_number or "",
        "YES" if approval_required else "NO"
    ])
