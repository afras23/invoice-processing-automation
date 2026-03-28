"""
Async Google Sheets client (mock implementation).

In production this would use the gspread-asyncio or Google Sheets API v4
directly.  The mock logs every row appended so behaviour is observable in
tests and development without real credentials.

Usage:
    client = SheetsClient(document_name="Invoices")
    await client.append_row(["Acme Corp", "INV-001", "2026-03-01", "1500.00"])
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AppendRowRequest(BaseModel):
    """Validated request to append a row to a sheet."""

    row: list[str] = Field(..., description="Column values to append")
    sheet_name: str = Field(default="Sheet1", description="Target sheet tab name")


class AppendRowResult(BaseModel):
    """Outcome of a successful append operation."""

    document_name: str
    sheet_name: str
    row_count: int = Field(..., description="Total rows after append (simulated)")
    appended_values: list[str]


class SheetsClient:
    """
    Async Google Sheets client.

    Currently mocked — records all appended rows in-memory so tests can
    assert on exported data without real API credentials.
    """

    def __init__(self, document_name: str = "Invoices") -> None:
        """
        Args:
            document_name: Name of the Google Sheets document to write to.
        """
        self._document_name = document_name
        self._rows: list[list[str]] = []

    @property
    def document_name(self) -> str:
        """Document this client is configured to write to."""
        return self._document_name

    @property
    def appended_rows(self) -> list[list[str]]:
        """All rows appended so far (for test assertions)."""
        return list(self._rows)

    async def append_row(
        self,
        row: list[str],
        sheet_name: str = "Sheet1",
    ) -> AppendRowResult:
        """
        Append a row to the configured Google Sheet.

        Args:
            row: Column values to append as strings.
            sheet_name: Target sheet tab (default "Sheet1").

        Returns:
            AppendRowResult with document, sheet, and appended values.
        """
        request = AppendRowRequest(row=row, sheet_name=sheet_name)
        self._rows.append(request.row)

        logger.info(
            "SheetsClient: row appended",
            extra={
                "document": self._document_name,
                "sheet": sheet_name,
                "columns": len(request.row),
                "total_rows": len(self._rows),
            },
        )
        return AppendRowResult(
            document_name=self._document_name,
            sheet_name=sheet_name,
            row_count=len(self._rows),
            appended_values=request.row,
        )
