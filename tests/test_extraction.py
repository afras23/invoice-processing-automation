"""
Tests for the extraction service.

All tests mock the Anthropic client so no real API calls are made.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import ExtractionError
from app.models.invoice import ExtractedInvoice
from app.services.extraction import extract_invoice_fields


def _make_client(response_json: dict) -> MagicMock:
    """Return a mock Anthropic client that returns *response_json* as text."""
    message = MagicMock()
    message.content = [MagicMock(text=json.dumps(response_json))]
    message.usage = MagicMock(input_tokens=100, output_tokens=50)
    client = MagicMock()
    client.messages.create.return_value = message
    return client


def test_valid_response_returns_extracted_invoice():
    client = _make_client(
        {"vendor": "Acme Corp", "invoice_id": "INV-001", "date": "2026-03-01", "amount": 1500.0}
    )
    result = extract_invoice_fields("some invoice text", client=client)

    assert isinstance(result, ExtractedInvoice)
    assert result.vendor == "Acme Corp"
    assert result.invoice_id == "INV-001"
    assert result.date == "2026-03-01"
    assert result.amount == 1500.0


def test_partial_response_sets_missing_fields_to_none():
    client = _make_client({"vendor": "PartialCo", "invoice_id": None, "date": None, "amount": None})
    result = extract_invoice_fields("partial invoice", client=client)

    assert result.vendor == "PartialCo"
    assert result.invoice_id is None
    assert result.date is None
    assert result.amount is None


def test_invalid_json_raises_extraction_error():
    message = MagicMock()
    message.content = [MagicMock(text="not json at all")]
    message.usage = MagicMock(input_tokens=10, output_tokens=5)
    client = MagicMock()
    client.messages.create.return_value = message

    with pytest.raises(ExtractionError, match="invalid JSON"):
        extract_invoice_fields("some text", client=client)


def test_api_error_raises_extraction_error():
    import anthropic

    client = MagicMock()
    client.messages.create.side_effect = anthropic.APIError(
        message="rate limited", request=MagicMock(), body=None
    )

    with pytest.raises(ExtractionError, match="API call failed"):
        extract_invoice_fields("some text", client=client)


def test_extra_keys_in_response_are_silently_ignored():
    client = _make_client(
        {
            "vendor": "Acme",
            "invoice_id": "X1",
            "date": "2026-01-01",
            "amount": 50.0,
            "unexpected_field": "ignored",
        }
    )
    result = extract_invoice_fields("text", client=client)
    assert result.vendor == "Acme"
