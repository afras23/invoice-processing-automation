"""
Error recovery tests.

Covers: AI timeout retry succeeds on second attempt, circuit breaker opens
after threshold failures, database unavailable returns graceful degraded status.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import anthropic
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.exceptions import CircuitBreakerOpenError, CostLimitExceededError
from app.services.ai.client import AnthropicClient
from app.services.batch_service import BatchService
from app.services.deduplication import DeduplicationStore
from app.services.extraction_service import process_invoice

# ── AI retry: timeout → success on second attempt ─────────────────────────────


async def test_ai_timeout_retry_succeeds_on_second_attempt() -> None:
    """A transient API error on the first call is retried; the second call succeeds."""
    raw_client = AsyncMock()
    test_settings = Settings(
        anthropic_api_key="test-key",
        ai_max_retries=2,
        ai_retry_base_delay_seconds=0.0,
        ai_circuit_breaker_threshold=10,
        ai_circuit_breaker_reset_seconds=60.0,
    )
    ai_client = AnthropicClient(anthropic_client=raw_client, settings=test_settings)

    success_message = AsyncMock()
    success_message.content = [
        AsyncMock(
            text=json.dumps(
                {
                    "vendor": "Acme Corp",
                    "invoice_id": "INV-001",
                    "date": "2026-03-01",
                    "amount": 500.0,
                }
            )
        )
    ]
    success_message.usage = AsyncMock(input_tokens=50, output_tokens=20)

    # First call raises, second succeeds
    raw_client.messages.create.side_effect = [
        anthropic.APIConnectionError(request=AsyncMock()),
        success_message,
    ]

    result = await ai_client.complete("system", "user", prompt_version="v1")
    assert result.content is not None
    assert "Acme Corp" in result.content


async def test_ai_retry_exhausted_raises_extraction_error() -> None:
    """When all retries fail, ExtractionError is raised (not a raw API error)."""
    from app.core.exceptions import ExtractionError

    raw_client = AsyncMock()
    test_settings = Settings(
        anthropic_api_key="test-key",
        ai_max_retries=2,
        ai_retry_base_delay_seconds=0.0,
        ai_circuit_breaker_threshold=10,
        ai_circuit_breaker_reset_seconds=60.0,
    )
    ai_client = AnthropicClient(anthropic_client=raw_client, settings=test_settings)
    raw_client.messages.create.side_effect = anthropic.APIConnectionError(request=AsyncMock())

    with pytest.raises(ExtractionError):
        await ai_client.complete("system", "user", prompt_version="v1")


# ── Circuit breaker ───────────────────────────────────────────────────────────


async def test_circuit_breaker_opens_after_repeated_failures() -> None:
    """After N consecutive failures the circuit breaker opens and blocks new calls."""
    from app.core.exceptions import ExtractionError

    raw_client = AsyncMock()
    threshold = 3
    test_settings = Settings(
        anthropic_api_key="test-key",
        ai_max_retries=1,
        ai_retry_base_delay_seconds=0.0,
        ai_circuit_breaker_threshold=threshold,
        ai_circuit_breaker_reset_seconds=3600.0,
    )
    ai_client = AnthropicClient(anthropic_client=raw_client, settings=test_settings)
    raw_client.messages.create.side_effect = anthropic.APIConnectionError(request=AsyncMock())

    # Exhaust circuit breaker
    for _ in range(threshold):
        with pytest.raises(ExtractionError):
            await ai_client.complete("system", "user", prompt_version="v1")

    assert ai_client._circuit_breaker.is_open  # type: ignore[attr-defined]

    # Next call is blocked by the open circuit breaker — raises CircuitBreakerOpenError
    with pytest.raises(CircuitBreakerOpenError):
        await ai_client.complete("system", "user", prompt_version="v1")


async def test_circuit_breaker_closed_allows_calls() -> None:
    """A fresh client with closed circuit breaker allows calls through."""
    raw_client = AsyncMock()
    test_settings = Settings(
        anthropic_api_key="test-key",
        ai_max_retries=1,
        ai_retry_base_delay_seconds=0.0,
        ai_circuit_breaker_threshold=5,
        ai_circuit_breaker_reset_seconds=60.0,
    )
    ai_client = AnthropicClient(anthropic_client=raw_client, settings=test_settings)

    success_msg = AsyncMock()
    success_msg.content = [
        AsyncMock(
            text=json.dumps(
                {"vendor": "Acme", "invoice_id": "INV-1", "date": "2026-03-01", "amount": 100.0}
            )
        )
    ]
    success_msg.usage = AsyncMock(input_tokens=10, output_tokens=5)
    raw_client.messages.create.return_value = success_msg

    result = await ai_client.complete("sys", "usr", prompt_version="v1")
    assert result.cost_usd >= 0


# ── Database unavailable → health check degrades gracefully ──────────────────


def test_health_ready_with_unreachable_database_reports_error(
    test_client: TestClient,
) -> None:
    """If DATABASE_URL is set but unreachable, /health/ready reports the error."""
    from app.config import settings

    with patch.object(settings, "database_url", "postgresql+asyncpg://bad-host/db"):
        response = test_client.get("/api/v1/health/ready")
    body = response.json()
    # AI key is "test-key" so ai_provider fails, but database should also be checked
    assert "checks" in body
    # The endpoint must not crash (500) — it returns a structured response
    assert response.status_code == 200


def test_health_ready_without_database_url_reports_not_configured(
    test_client: TestClient,
) -> None:
    """When DATABASE_URL is absent, the database check reports 'not configured'."""
    from app.config import settings

    with patch.object(settings, "database_url", None):
        response = test_client.get("/api/v1/health/ready")
    body = response.json()
    assert body["checks"]["database"] == "not configured"


def test_pipeline_handles_extraction_error_gracefully() -> None:
    """process_invoice returns status='failed' on ExtractionError — no exception propagates."""

    async def _run() -> None:
        from app.core.exceptions import ExtractionError

        failing_client = AsyncMock()
        failing_client.complete.side_effect = ExtractionError("AI unavailable")

        result = await process_invoice(
            b"invoice text",
            filename="test.txt",
            dedup_store=DeduplicationStore(),
            ai_client=failing_client,
        )
        assert result.status == "failed"
        assert result.extracted is None

    import asyncio

    asyncio.get_event_loop().run_until_complete(_run())


# ── Daily cost limit ──────────────────────────────────────────────────────────


async def test_cost_limit_reached_raises_cost_limit_error() -> None:
    """When the daily cost limit is exceeded, CostLimitExceededError is raised."""
    raw_client = AsyncMock()
    test_settings = Settings(
        anthropic_api_key="test-key",
        max_daily_cost_usd=0.0,  # limit already at zero
        ai_max_retries=1,
        ai_retry_base_delay_seconds=0.0,
        ai_circuit_breaker_threshold=10,
        ai_circuit_breaker_reset_seconds=60.0,
    )
    ai_client = AnthropicClient(anthropic_client=raw_client, settings=test_settings)

    with pytest.raises(CostLimitExceededError):
        await ai_client.complete("system", "user", prompt_version="v1")


async def test_cost_limit_in_batch_marks_document_failed() -> None:
    """CostLimitExceededError in a batch is isolated per-document → status='failed'."""
    raw_client = AsyncMock()
    test_settings = Settings(
        anthropic_api_key="test-key",
        max_daily_cost_usd=0.0,
        ai_max_retries=1,
        ai_retry_base_delay_seconds=0.0,
        ai_circuit_breaker_threshold=10,
        ai_circuit_breaker_reset_seconds=60.0,
    )
    ai_client = AnthropicClient(anthropic_client=raw_client, settings=test_settings)

    svc = BatchService()
    job = svc.create_job(["inv.txt"])
    result = await svc.run(
        job.job_id,
        [("inv.txt", b"invoice text")],
        ai_client=ai_client,
        dedup_store=DeduplicationStore(),
    )
    assert result.failed == 1
    assert result.documents[0].status == "failed"
