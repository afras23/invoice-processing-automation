"""
Unit tests for the AnthropicClient AI wrapper.

Tests cover: successful call, retry on transient error, circuit breaker,
cost limit enforcement, and daily cost accumulation.  No real API calls
are made — the raw anthropic.AsyncAnthropic client is always mocked.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import anthropic
import pytest

from app.core.exceptions import (
    CircuitBreakerOpenError,
    CostLimitExceededError,
    ExtractionError,
)
from app.services.ai.client import AICallResult, AnthropicClient, CircuitBreaker

# ── helpers ───────────────────────────────────────────────────────────────────


def _raw_message(content: str, input_tokens: int = 100, output_tokens: int = 40) -> MagicMock:
    """Build a mock SDK Message object."""
    msg = MagicMock()
    msg.content = [MagicMock(text=content)]
    msg.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    return msg


def _make_client(test_settings, raw_anthropic: AsyncMock | None = None) -> AnthropicClient:
    """Build an AnthropicClient backed by a mock raw client."""
    if raw_anthropic is None:
        raw_anthropic = AsyncMock()
    return AnthropicClient(anthropic_client=raw_anthropic, settings=test_settings)


# ── successful call ───────────────────────────────────────────────────────────


async def test_successful_call_returns_ai_call_result(test_settings):
    payload = {"vendor": "Acme Corp", "invoice_id": "INV-1", "date": "2026-03-01", "amount": 500.0}
    raw = AsyncMock()
    raw.messages.create.return_value = _raw_message(json.dumps(payload))

    client = _make_client(test_settings, raw)
    result = await client.complete("system", "user", prompt_version="v1")

    assert isinstance(result, AICallResult)
    assert json.loads(result.content) == payload
    assert result.input_tokens == 100
    assert result.output_tokens == 40
    assert result.prompt_version == "v1"
    assert result.cost_usd > 0


async def test_successful_call_increments_daily_counters(test_settings):
    raw = AsyncMock()
    raw.messages.create.return_value = _raw_message('{"ok": true}')

    client = _make_client(test_settings, raw)
    assert client.daily_call_count == 0
    assert client.daily_cost_usd == 0.0

    await client.complete("sys", "user", prompt_version="v1")

    assert client.daily_call_count == 1
    assert client.daily_cost_usd > 0


async def test_cost_calculated_from_token_counts(test_settings):
    raw = AsyncMock()
    raw.messages.create.return_value = _raw_message("{}", input_tokens=1_000_000, output_tokens=0)

    client = _make_client(test_settings, raw)
    result = await client.complete("sys", "user", prompt_version="v1")

    # 1M input tokens at $3/M = $3.00
    assert abs(result.cost_usd - 3.0) < 0.001


# ── retry behaviour ───────────────────────────────────────────────────────────


async def test_retry_on_api_error_succeeds_on_second_attempt(test_settings):
    from app.config import Settings

    settings_with_retries = Settings(
        anthropic_api_key="test-key",
        ai_max_retries=3,
        ai_retry_base_delay_seconds=0.0,
        ai_circuit_breaker_threshold=10,
        max_daily_cost_usd=100.0,
    )
    good_msg = _raw_message('{"vendor": "Retry Corp"}')
    api_error = anthropic.APIError(message="transient", request=MagicMock(), body=None)

    raw = AsyncMock()
    raw.messages.create.side_effect = [api_error, good_msg]

    client = _make_client(settings_with_retries, raw)
    result = await client.complete("sys", "user", prompt_version="v1")

    assert json.loads(result.content)["vendor"] == "Retry Corp"
    assert raw.messages.create.call_count == 2


async def test_exhausted_retries_raises_extraction_error(test_settings):
    api_error = anthropic.APIError(message="persistent", request=MagicMock(), body=None)
    raw = AsyncMock()
    raw.messages.create.side_effect = api_error  # always fails

    client = _make_client(test_settings, raw)  # ai_max_retries=1

    with pytest.raises(ExtractionError, match="attempt"):
        await client.complete("sys", "user", prompt_version="v1")


# ── circuit breaker ───────────────────────────────────────────────────────────


async def test_circuit_breaker_opens_after_threshold_failures(test_settings):
    from app.config import Settings

    low_threshold_settings = Settings(
        anthropic_api_key="test-key",
        ai_max_retries=1,
        ai_retry_base_delay_seconds=0.0,
        ai_circuit_breaker_threshold=3,
        ai_circuit_breaker_reset_seconds=60.0,
        max_daily_cost_usd=100.0,
    )
    api_error = anthropic.APIError(message="fail", request=MagicMock(), body=None)
    raw = AsyncMock()
    raw.messages.create.side_effect = api_error

    client = _make_client(low_threshold_settings, raw)

    # Three failures to open the circuit
    for _ in range(3):
        with pytest.raises(ExtractionError):
            await client.complete("sys", "user", prompt_version="v1")

    assert client.circuit_breaker.is_open

    # Fourth call rejected immediately — circuit is open
    with pytest.raises(CircuitBreakerOpenError):
        await client.complete("sys", "user", prompt_version="v1")


def test_circuit_breaker_records_success_resets_count():
    cb = CircuitBreaker(failure_threshold=3, reset_timeout_seconds=60.0)
    cb.record_failure()
    cb.record_failure()
    assert cb.failure_count == 2

    cb.record_success()
    assert cb.failure_count == 0
    assert not cb.is_open


def test_circuit_breaker_check_raises_when_open():
    cb = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=60.0)
    cb.record_failure()
    assert cb.is_open

    with pytest.raises(CircuitBreakerOpenError):
        cb.check()


# ── cost limit ────────────────────────────────────────────────────────────────


async def test_cost_limit_blocks_call_when_budget_exhausted(test_settings):
    from app.config import Settings

    zero_budget_settings = Settings(
        anthropic_api_key="test-key",
        ai_max_retries=1,
        ai_retry_base_delay_seconds=0.0,
        ai_circuit_breaker_threshold=10,
        max_daily_cost_usd=0.0,  # exhausted from the start
    )
    raw = AsyncMock()
    client = _make_client(zero_budget_settings, raw)

    with pytest.raises(CostLimitExceededError):
        await client.complete("sys", "user", prompt_version="v1")

    # Raw client never called — rejected before the network hit
    raw.messages.create.assert_not_called()


async def test_daily_cost_accumulates_across_calls(test_settings):
    raw = AsyncMock()
    raw.messages.create.return_value = _raw_message("{}", input_tokens=100, output_tokens=100)

    client = _make_client(test_settings, raw)

    await client.complete("sys", "user1", prompt_version="v1")
    cost_after_first = client.daily_cost_usd

    await client.complete("sys", "user2", prompt_version="v1")
    cost_after_second = client.daily_cost_usd

    assert cost_after_second > cost_after_first
    assert client.daily_call_count == 2


# ── get_metrics ───────────────────────────────────────────────────────────────


async def test_get_metrics_returns_cost_snapshot(test_settings):
    raw = AsyncMock()
    raw.messages.create.return_value = _raw_message("{}")

    client = _make_client(test_settings, raw)
    await client.complete("sys", "user", prompt_version="v1")

    metrics = client.get_metrics()
    assert "daily_cost_usd" in metrics
    assert "limit_usd" in metrics
    assert "utilisation_pct" in metrics
    assert "circuit_breaker_open" in metrics
    assert metrics["daily_call_count"] == 1
