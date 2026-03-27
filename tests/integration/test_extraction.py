"""
Integration tests for the extract_invoice_fields function.

All tests mock the AnthropicClient so no real API calls are made.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import ExtractionError
from app.models.invoice import ExtractedInvoice
from app.services.ai.client import AICallResult, AnthropicClient
from app.services.extraction_service import extract_invoice_fields


def _ai_result(response_dict: dict) -> AICallResult:
    return AICallResult(
        content=json.dumps(response_dict),
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.0005,
        latency_ms=480.0,
        model="claude-test",
        prompt_version="v1",
    )


def _mock_client(response_dict: dict) -> AsyncMock:
    client = AsyncMock(spec=AnthropicClient)
    client.complete.return_value = _ai_result(response_dict)
    return client


# ── happy path ────────────────────────────────────────────────────────────────


async def test_valid_response_returns_extracted_invoice():
    client = _mock_client(
        {"vendor": "Acme Corp", "invoice_id": "INV-001", "date": "2026-03-01", "amount": 1500.0}
    )
    result = await extract_invoice_fields("some invoice text", ai_client=client)

    assert isinstance(result, ExtractedInvoice)
    assert result.vendor == "Acme Corp"
    assert result.invoice_id == "INV-001"
    assert result.date == "2026-03-01"
    assert result.amount == 1500.0


async def test_partial_response_sets_missing_fields_to_none():
    client = _mock_client({"vendor": "PartialCo", "invoice_id": None, "date": None, "amount": None})
    result = await extract_invoice_fields("partial invoice", ai_client=client)

    assert result.vendor == "PartialCo"
    assert result.invoice_id is None
    assert result.date is None
    assert result.amount is None


async def test_extra_keys_in_response_are_silently_ignored():
    client = _mock_client(
        {
            "vendor": "Acme",
            "invoice_id": "X1",
            "date": "2026-01-01",
            "amount": 50.0,
            "unexpected_field": "ignored",
        }
    )
    result = await extract_invoice_fields("text", ai_client=client)
    assert result.vendor == "Acme"


# ── error handling ────────────────────────────────────────────────────────────


async def test_invalid_json_raises_extraction_error():
    client = AsyncMock(spec=AnthropicClient)
    client.complete.return_value = AICallResult(
        content="not json at all",
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.0001,
        latency_ms=100.0,
        model="test",
        prompt_version="v1",
    )

    with pytest.raises(ExtractionError, match="invalid JSON"):
        await extract_invoice_fields("some text", ai_client=client)


async def test_client_error_propagates_as_extraction_error():
    client = AsyncMock(spec=AnthropicClient)
    client.complete.side_effect = ExtractionError("AI call failed after 1 attempt(s)")

    with pytest.raises(ExtractionError):
        await extract_invoice_fields("some text", ai_client=client)


# ── prompt version ────────────────────────────────────────────────────────────


async def test_prompt_version_passed_to_ai_client():
    client = _mock_client(
        {"vendor": "V2Co", "invoice_id": "X", "date": "2026-01-01", "amount": 1.0}
    )
    await extract_invoice_fields("text", ai_client=client, prompt_version="v2")

    call_kwargs = client.complete.call_args.kwargs
    assert call_kwargs["prompt_version"] == "v2"
