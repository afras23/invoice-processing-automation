"""
Shared fixtures for the test suite.

Provides mock AI clients, sample invoice text, HTTP test client, and Pydantic
model helpers used across unit and integration tests.
"""

from __future__ import annotations

import json
import os
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock

# Set test env vars before any app module is imported, so Settings() can
# be instantiated without a real API key.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.services.ai.client import AICallResult, AnthropicClient  # noqa: E402
from app.services.batch_service import BatchService  # noqa: E402
from app.services.deduplication import DeduplicationStore  # noqa: E402
from app.services.metrics_service import MetricsTracker  # noqa: E402
from app.services.review_service import ReviewService  # noqa: E402

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "sample_inputs"


# ── Settings ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def test_settings() -> Settings:
    """Test settings with safe cost and retry defaults."""
    return Settings(
        app_env="test",
        anthropic_api_key="test-key",
        ai_model="claude-test",
        max_daily_cost_usd=100.0,
        ai_max_retries=1,
        ai_retry_base_delay_seconds=0.0,
        ai_circuit_breaker_threshold=10,
        ai_circuit_breaker_reset_seconds=60.0,
    )


# ── AI client helpers ─────────────────────────────────────────────────────────


def make_ai_result(response_dict: dict, *, prompt_version: str = "v1") -> AICallResult:
    """Build an AICallResult whose content is *response_dict* serialised as JSON."""
    return AICallResult(
        content=json.dumps(response_dict),
        input_tokens=100,
        output_tokens=40,
        cost_usd=0.0004,
        latency_ms=450.0,
        model="claude-test",
        prompt_version=prompt_version,
    )


def make_mock_ai_client(response_dict: dict, *, prompt_version: str = "v1") -> AsyncMock:
    """Return an AsyncMock AnthropicClient that returns *response_dict* as JSON."""
    mock_client = AsyncMock(spec=AnthropicClient)
    mock_client.complete.return_value = make_ai_result(response_dict, prompt_version=prompt_version)
    mock_client.get_metrics.return_value = {
        "daily_cost_usd": 0.0,
        "daily_call_count": 0,
        "limit_usd": 10.0,
        "utilisation_pct": 0.0,
        "circuit_breaker_open": False,
    }
    return mock_client


@pytest.fixture()
def good_ai_client() -> AsyncMock:
    """Mock AI client returning a complete, valid invoice extraction."""
    return make_mock_ai_client(
        {"vendor": "Acme Corp", "invoice_id": "INV-001", "date": "2026-03-01", "amount": 1500.0}
    )


# ── Deduplication ─────────────────────────────────────────────────────────────


@pytest.fixture()
def dedup_store() -> DeduplicationStore:
    """Fresh DeduplicationStore for each test."""
    return DeduplicationStore()


# ── Service fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def review_service() -> ReviewService:
    """Fresh ReviewService for each test."""
    return ReviewService()


@pytest.fixture()
def batch_service() -> BatchService:
    """Fresh BatchService for each test."""
    return BatchService()


@pytest.fixture()
def metrics_tracker() -> MetricsTracker:
    """Fresh MetricsTracker for each test."""
    return MetricsTracker()


# ── HTTP test client ──────────────────────────────────────────────────────────


@pytest.fixture()
def test_client(
    good_ai_client: AsyncMock, dedup_store: DeduplicationStore
) -> Generator[TestClient, None, None]:
    """
    FastAPI TestClient with AI client and dedup store overridden to safe mocks.

    All HTTP-level tests should use this fixture to avoid real API calls.
    """
    from app.dependencies import (
        get_ai_client,
        get_batch_service,
        get_dedup_store,
        get_metrics_tracker,
        get_review_service,
    )
    from app.main import app
    from app.services.batch_service import BatchService
    from app.services.metrics_service import MetricsTracker
    from app.services.review_service import ReviewService

    fresh_batch_svc = BatchService()
    fresh_review_svc = ReviewService()
    fresh_metrics = MetricsTracker()

    app.dependency_overrides[get_ai_client] = lambda: good_ai_client
    app.dependency_overrides[get_dedup_store] = lambda: dedup_store
    app.dependency_overrides[get_batch_service] = lambda: fresh_batch_svc
    app.dependency_overrides[get_review_service] = lambda: fresh_review_svc
    app.dependency_overrides[get_metrics_tracker] = lambda: fresh_metrics

    client = TestClient(app, raise_server_exceptions=False)
    yield client  # type: ignore[misc]

    app.dependency_overrides.clear()


# ── Sample text ───────────────────────────────────────────────────────────────


@pytest.fixture()
def sample_invoice_text() -> str:
    return (
        "INVOICE\n"
        "Vendor: Acme Corp\n"
        "Invoice No: INV-2026-0042\n"
        "Date: 2026-03-01\n"
        "Amount Due: 1500.00\n"
    )


@pytest.fixture()
def minimal_invoice_text() -> str:
    """Only the amount — vendor, id, and date are absent."""
    return "Total: 99.99"


@pytest.fixture()
def pdf_magic_bytes() -> bytes:
    """Bytes that look like a PDF header (not a real PDF)."""
    return b"%PDF-fake content that is not a real PDF"
