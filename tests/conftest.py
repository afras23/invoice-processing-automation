"""
Shared fixtures for the test suite.

Provides mock AI clients, sample invoice text, and Pydantic model helpers
used across unit and integration tests.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

# Set test env vars before any app module is imported, so Settings() can
# be instantiated without a real API key.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import pytest  # noqa: E402

from app.config import Settings  # noqa: E402
from app.services.ai.client import AICallResult, AnthropicClient  # noqa: E402
from app.services.deduplication import DeduplicationStore  # noqa: E402

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
