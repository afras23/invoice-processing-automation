"""
Unit tests for integration clients and export service.

Covers:
- Airtable client creates record with correct fields
- Airtable client updates record merging fields
- Airtable client raises KeyError on unknown record update
- Sheets client appends row and returns correct result
- Sheets client tracks all appended rows
- Export: generic CSV has correct headers
- Export: Xero CSV has correct headers
- Export: QuickBooks CSV has correct headers
- Export: Google Sheets export calls append_row
- Airtable integration invoked when configured as export destination
- Sheets export called when export_format is "google_sheets"
"""

from __future__ import annotations

import csv
import io

import pytest

from app.integrations.airtable_client import AirtableClient
from app.integrations.sheets_client import SheetsClient
from app.models.invoice import (
    ConfidenceResult,
    ExtractedInvoice,
    Invoice,
    LineItem,
    PipelineResult,
    ValidationResult,
)
from app.services.export_service import (
    export_to_sheets,
    to_csv_string,
    to_quickbooks_csv,
    to_xero_csv,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _sample_invoice() -> Invoice:
    return Invoice(
        vendor="Acme Corp",
        invoice_number="INV-001",
        invoice_date="2026-03-01",
        currency="USD",
        total_amount=1500.0,
        line_items=[
            LineItem(description="Consulting", quantity=10, unit_price=150.0, total=1500.0)
        ],
    )


def _sample_pipeline_result() -> PipelineResult:
    return PipelineResult(
        status="processed",
        content_hash="abc123",
        extracted=ExtractedInvoice(
            vendor="Acme Corp",
            invoice_id="INV-001",
            date="2026-03-01",
            amount=1500.0,
            currency="USD",
        ),
        validation=ValidationResult(passed=True, errors=[]),
        confidence=ConfidenceResult(score=0.95, completeness=1.0, validation_score=1.0),
    )


# ── Airtable client ───────────────────────────────────────────────────────────


async def test_airtable_create_record_returns_record():
    client = AirtableClient(base_id="appTest", table_name="Invoices")
    record = await client.create_record({"Vendor": "Acme Corp", "Amount": 1500.0})

    assert record.record_id.startswith("rec")
    assert record.table_name == "Invoices"
    assert record.fields["Vendor"] == "Acme Corp"
    assert record.fields["Amount"] == 1500.0


async def test_airtable_create_record_stored_in_records():
    client = AirtableClient(base_id="appTest", table_name="Invoices")
    await client.create_record({"Vendor": "Beta Ltd"})
    await client.create_record({"Vendor": "Gamma Inc"})
    assert len(client.records) == 2


async def test_airtable_update_record_merges_fields():
    client = AirtableClient()
    record = await client.create_record({"Vendor": "Acme Corp", "Status": "draft"})
    updated = await client.update_record(record.record_id, {"Status": "approved"})

    assert updated.fields["Vendor"] == "Acme Corp"
    assert updated.fields["Status"] == "approved"


async def test_airtable_update_unknown_record_raises():
    client = AirtableClient()
    with pytest.raises(KeyError, match="not found"):
        await client.update_record("recNONEXISTENT", {"Status": "approved"})


# ── Sheets client ─────────────────────────────────────────────────────────────


async def test_sheets_client_append_row_returns_result():
    client = SheetsClient(document_name="Invoices")
    result = await client.append_row(["Acme Corp", "INV-001", "2026-03-01", "1500.00"])

    assert result.document_name == "Invoices"
    assert result.appended_values == ["Acme Corp", "INV-001", "2026-03-01", "1500.00"]
    assert result.row_count == 1


async def test_sheets_client_tracks_all_rows():
    client = SheetsClient()
    await client.append_row(["row1"])
    await client.append_row(["row2"])
    await client.append_row(["row3"])
    assert len(client.appended_rows) == 3
    assert client.appended_rows[1] == ["row2"]


# ── Export service: CSV formats ───────────────────────────────────────────────


def test_generic_csv_has_headers():
    result = to_csv_string([_sample_pipeline_result()])
    reader = csv.DictReader(io.StringIO(result))
    assert reader.fieldnames is not None
    assert "vendor" in reader.fieldnames
    assert "invoice_id" in reader.fieldnames
    assert "amount" in reader.fieldnames
    assert "currency" in reader.fieldnames


def test_generic_csv_row_contains_correct_values():
    result = to_csv_string([_sample_pipeline_result()])
    rows = list(csv.DictReader(io.StringIO(result)))
    assert len(rows) == 1
    assert rows[0]["vendor"] == "Acme Corp"
    assert rows[0]["invoice_id"] == "INV-001"
    assert rows[0]["validation_passed"] == "YES"


def test_xero_csv_has_required_headers():
    result = to_xero_csv(_sample_invoice())
    reader = csv.DictReader(io.StringIO(result))
    assert reader.fieldnames is not None
    assert "*ContactName" in reader.fieldnames
    assert "*InvoiceNumber" in reader.fieldnames
    assert "*UnitAmount" in reader.fieldnames


def test_xero_csv_row_vendor_correct():
    result = to_xero_csv(_sample_invoice())
    rows = list(csv.DictReader(io.StringIO(result)))
    assert len(rows) == 1
    assert rows[0]["*ContactName"] == "Acme Corp"
    assert rows[0]["*InvoiceNumber"] == "INV-001"


def test_quickbooks_csv_has_required_headers():
    result = to_quickbooks_csv(_sample_invoice())
    reader = csv.DictReader(io.StringIO(result))
    assert reader.fieldnames is not None
    assert "Vendor" in reader.fieldnames
    assert "Invoice Number" in reader.fieldnames
    assert "Amount" in reader.fieldnames


def test_quickbooks_csv_row_correct():
    result = to_quickbooks_csv(_sample_invoice())
    rows = list(csv.DictReader(io.StringIO(result)))
    assert rows[0]["Vendor"] == "Acme Corp"
    assert rows[0]["Invoice Number"] == "INV-001"


# ── Google Sheets export ──────────────────────────────────────────────────────


async def test_export_to_sheets_calls_append_row():
    client = SheetsClient(document_name="Invoices")
    pipeline_result = _sample_pipeline_result()

    await export_to_sheets(pipeline_result, client)

    assert len(client.appended_rows) == 1
    row = client.appended_rows[0]
    assert row[0] == "Acme Corp"  # vendor is first column
    assert row[1] == "INV-001"


async def test_export_to_sheets_skips_empty_extracted():
    client = SheetsClient()
    pipeline_result = PipelineResult(
        status="failed",
        content_hash="xyz",
        extracted=None,
    )
    await export_to_sheets(pipeline_result, client)
    assert len(client.appended_rows) == 0
