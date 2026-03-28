"""
Integration tests for the invoice processing pipeline.

The AI extraction step is always mocked — no real API calls are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from app.services.extraction_service import process_invoice
from tests.conftest import make_mock_ai_client

# ── happy path ────────────────────────────────────────────────────────────────


async def test_valid_invoice_returns_processed_status(dedup_store, good_ai_client):
    result = await process_invoice(
        "Invoice from Acme Corp, total 1500.00",
        dedup_store=dedup_store,
        ai_client=good_ai_client,
    )
    assert result.status == "processed"


async def test_processed_result_has_all_sections(dedup_store, good_ai_client):
    result = await process_invoice(
        "Invoice from Acme Corp, total 1500.00",
        dedup_store=dedup_store,
        ai_client=good_ai_client,
    )
    assert result.extracted is not None
    assert result.validation is not None
    assert result.confidence is not None
    assert result.csv_row is not None


async def test_processed_result_extracted_fields_correct(dedup_store, good_ai_client):
    result = await process_invoice(
        "some invoice text",
        dedup_store=dedup_store,
        ai_client=good_ai_client,
    )
    assert result.extracted is not None
    assert result.extracted.vendor == "Acme Corp"
    assert result.extracted.invoice_id == "INV-001"
    assert result.extracted.amount == 1500.0


async def test_valid_invoice_has_confidence_score_of_1(dedup_store, good_ai_client):
    result = await process_invoice("some text", dedup_store=dedup_store, ai_client=good_ai_client)
    assert result.confidence is not None
    assert result.confidence.score == 1.0


async def test_csv_row_has_seven_columns(dedup_store, good_ai_client):
    result = await process_invoice("some text", dedup_store=dedup_store, ai_client=good_ai_client)
    assert result.csv_row is not None
    assert len(result.csv_row) == 7


# ── deduplication ─────────────────────────────────────────────────────────────


async def test_duplicate_submission_returns_duplicate_status(dedup_store, good_ai_client):
    invoice_text = "Invoice from Acme Corp"
    await process_invoice(invoice_text, dedup_store=dedup_store, ai_client=good_ai_client)
    result = await process_invoice(invoice_text, dedup_store=dedup_store, ai_client=good_ai_client)
    assert result.status == "duplicate"


async def test_duplicate_result_has_same_content_hash(dedup_store, good_ai_client):
    invoice_text = "Invoice from Acme Corp"
    first = await process_invoice(invoice_text, dedup_store=dedup_store, ai_client=good_ai_client)
    second = await process_invoice(invoice_text, dedup_store=dedup_store, ai_client=good_ai_client)
    assert second.content_hash == first.content_hash


async def test_different_invoices_are_not_duplicates(dedup_store, good_ai_client):
    r1 = await process_invoice("Invoice A — 100", dedup_store=dedup_store, ai_client=good_ai_client)
    r2 = await process_invoice("Invoice B — 200", dedup_store=dedup_store, ai_client=good_ai_client)
    assert r1.status == "processed"
    assert r2.status == "processed"


# ── partial / missing fields ──────────────────────────────────────────────────


async def test_missing_fields_lower_confidence(dedup_store):
    partial_client = make_mock_ai_client(
        {"vendor": None, "invoice_id": None, "date": None, "amount": 50.0}
    )
    result = await process_invoice(
        "partial invoice", dedup_store=dedup_store, ai_client=partial_client
    )
    assert result.status == "processed"
    assert result.confidence is not None
    assert result.confidence.score < 1.0


async def test_all_null_fields_fails_validation(dedup_store):
    null_client = make_mock_ai_client(
        {"vendor": None, "invoice_id": None, "date": None, "amount": None}
    )
    result = await process_invoice("unreadable doc", dedup_store=dedup_store, ai_client=null_client)
    assert result.validation is not None
    assert result.validation.passed is False
    assert result.confidence is not None
    assert result.confidence.score == 0.0


async def test_invalid_json_from_ai_returns_failed_status(dedup_store):
    bad_client = AsyncMock()
    from app.services.ai.client import AICallResult

    bad_client.complete.return_value = AICallResult(
        content="this is not json",
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.0001,
        latency_ms=100.0,
        model="test",
        prompt_version="v1",
    )
    result = await process_invoice("some invoice", dedup_store=dedup_store, ai_client=bad_client)
    assert result.status == "failed"
