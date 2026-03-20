"""
Tests for the invoice processing pipeline.

The AI extraction step is always mocked — no real API calls are made.
"""

import json
from unittest.mock import MagicMock

import pytest

from app.services.deduplication import DeduplicationStore
from app.services.pipeline import process_invoice


def _ai_client(response: dict) -> MagicMock:
    """Mock Anthropic client returning *response* as JSON text."""
    message = MagicMock()
    message.content = [MagicMock(text=json.dumps(response))]
    message.usage = MagicMock(input_tokens=100, output_tokens=40)
    client = MagicMock()
    client.messages.create.return_value = message
    return client


def _good_client() -> MagicMock:
    return _ai_client(
        {"vendor": "Acme Corp", "invoice_id": "INV-001", "date": "2026-03-01", "amount": 1500.0}
    )


@pytest.fixture()
def store() -> DeduplicationStore:
    return DeduplicationStore()


# ── happy path ────────────────────────────────────────────────────────────────

def test_valid_invoice_returns_processed_status(store):
    result = process_invoice(
        "Invoice from Acme Corp, total 1500.00",
        dedup_store=store,
        ai_client=_good_client(),
    )
    assert result.status == "processed"


def test_processed_result_has_all_sections(store):
    result = process_invoice(
        "Invoice from Acme Corp, total 1500.00",
        dedup_store=store,
        ai_client=_good_client(),
    )
    assert result.extracted is not None
    assert result.validation is not None
    assert result.confidence is not None
    assert result.csv_row is not None


def test_processed_result_extracted_fields_are_correct(store):
    result = process_invoice(
        "some text",
        dedup_store=store,
        ai_client=_good_client(),
    )
    assert result.extracted.vendor == "Acme Corp"
    assert result.extracted.invoice_id == "INV-001"
    assert result.extracted.amount == 1500.0


def test_valid_invoice_has_high_confidence(store):
    result = process_invoice("some text", dedup_store=store, ai_client=_good_client())
    assert result.confidence.score == 1.0


def test_csv_row_has_six_columns(store):
    result = process_invoice("some text", dedup_store=store, ai_client=_good_client())
    assert len(result.csv_row) == 6


# ── deduplication ─────────────────────────────────────────────────────────────

def test_duplicate_submission_returns_duplicate_status(store):
    text = "Invoice from Acme Corp"
    process_invoice(text, dedup_store=store, ai_client=_good_client())
    result = process_invoice(text, dedup_store=store, ai_client=_good_client())
    assert result.status == "duplicate"


def test_duplicate_result_has_content_hash(store):
    text = "Invoice from Acme Corp"
    first = process_invoice(text, dedup_store=store, ai_client=_good_client())
    second = process_invoice(text, dedup_store=store, ai_client=_good_client())
    assert second.content_hash == first.content_hash


def test_different_invoices_are_not_duplicates(store):
    r1 = process_invoice("Invoice A — amount 100", dedup_store=store, ai_client=_good_client())
    r2 = process_invoice("Invoice B — amount 200", dedup_store=store, ai_client=_good_client())
    assert r1.status == "processed"
    assert r2.status == "processed"


# ── missing / malformed fields ────────────────────────────────────────────────

def test_missing_fields_lower_confidence(store):
    client = _ai_client({"vendor": None, "invoice_id": None, "date": None, "amount": 50.0})
    result = process_invoice("partial invoice", dedup_store=store, ai_client=client)
    assert result.status == "processed"
    assert result.confidence.score < 1.0


def test_all_null_fields_fails_validation(store):
    client = _ai_client({"vendor": None, "invoice_id": None, "date": None, "amount": None})
    result = process_invoice("unreadable doc", dedup_store=store, ai_client=client)
    assert result.validation.passed is False
    assert result.confidence.score == 0.0


def test_invalid_json_from_ai_returns_failed_status(store):
    message = MagicMock()
    message.content = [MagicMock(text="this is not json")]
    message.usage = MagicMock(input_tokens=10, output_tokens=5)
    bad_client = MagicMock()
    bad_client.messages.create.return_value = message

    result = process_invoice("some invoice", dedup_store=store, ai_client=bad_client)
    assert result.status == "failed"
