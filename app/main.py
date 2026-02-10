from fastapi import FastAPI, UploadFile
import shutil
from app.extract import extract_invoice_data
from app.validate import validate_invoice
from app.approval import requires_approval
from app.sheets import write_to_sheet
from app.slack import send_slack_message
from app.models import Invoice

app = FastAPI()

@app.post("/upload-invoice/")
async def upload_invoice(file: UploadFile):
    path = f"tmp_{file.filename}"

    with open(path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    data = extract_invoice_data(path)
    invoice = Invoice(**data)

    issues = validate_invoice(invoice)
    approval = requires_approval(invoice.total_amount)

    write_to_sheet(invoice, approval)

    send_slack_message(
        f"Invoice processed: {invoice.vendor} | £{invoice.total_amount} | Approval: {approval}"
    )

    return {
        "status": "processed",
        "approval_required": approval,
        "issues": issues
    }
