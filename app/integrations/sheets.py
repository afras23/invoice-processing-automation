"""
Google Sheets integration.

Appends processed invoice records to a configured spreadsheet.
"""

import logging

from app.config import settings
from app.core.exceptions import IntegrationError
from app.models.invoice import Invoice

logger = logging.getLogger(__name__)


def write_to_sheet(invoice: Invoice, approval_required: bool) -> None:
    """
    Append an invoice row to the configured Google Sheet.

    Silently skips if SERVICE_ACCOUNT_FILE is not configured or the
    credentials file is absent — useful in environments where Sheets
    integration is optional.

    Args:
        invoice: Validated Invoice model.
        approval_required: Whether manual approval is needed.

    Raises:
        IntegrationError: If the Sheets API call fails.
    """
    import os

    if not os.path.exists(settings.service_account_file):
        logger.warning(
            "Sheets integration skipped: service account file not found",
            extra={"path": settings.service_account_file},
        )
        return

    try:
        import gspread
        from oauth2client.service_account import ServiceAccountCredentials

        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            settings.service_account_file, scope
        )
        client = gspread.authorize(creds)
        sheet = client.open(settings.sheets_document_name).sheet1

        sheet.append_row(
            [
                invoice.vendor,
                invoice.invoice_number,
                invoice.invoice_date,
                invoice.currency,
                invoice.total_amount,
                invoice.po_number or "",
                "YES" if approval_required else "NO",
            ]
        )

        logger.info(
            "Invoice written to Sheets",
            extra={"invoice_number": invoice.invoice_number},
        )

    except Exception as e:
        raise IntegrationError(f"Failed to write to Google Sheets: {e}") from e
