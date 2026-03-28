"""
FastAPI dependency providers.

All stateful objects are constructed once and injected via Depends(). Tests
override these by calling app.dependency_overrides rather than patching
module-level singletons.
"""

from __future__ import annotations

from functools import lru_cache

import anthropic

from app.config import settings
from app.integrations.airtable_client import AirtableClient
from app.integrations.sheets_client import SheetsClient
from app.services.ai.client import AnthropicClient
from app.services.batch_service import BatchService
from app.services.batch_service import get_batch_service as _get_batch_svc
from app.services.deduplication import DeduplicationStore
from app.services.metrics_service import MetricsTracker
from app.services.metrics_service import get_metrics_tracker as _get_metrics_tracker
from app.services.review_service import ReviewService
from app.services.review_service import get_review_service as _get_review_svc

# ── AI client ─────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def get_ai_client() -> AnthropicClient:
    """
    Return the process-wide AI client, creating it on first call.

    Returns:
        AnthropicClient configured from Settings.
    """
    raw_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return AnthropicClient(anthropic_client=raw_client, settings=settings)


# ── Deduplication store ───────────────────────────────────────────────────────

_dedup_store = DeduplicationStore()


def get_dedup_store() -> DeduplicationStore:
    """
    Return the process-wide deduplication store.

    Returns:
        DeduplicationStore instance (in-memory; not safe for multi-instance deploys).
    """
    return _dedup_store


# ── Service singletons ────────────────────────────────────────────────────────


def get_metrics_tracker() -> MetricsTracker:
    """Return the process-wide metrics tracker."""
    return _get_metrics_tracker()


def get_review_service() -> ReviewService:
    """Return the process-wide review service."""
    return _get_review_svc()


def get_batch_service() -> BatchService:
    """Return the process-wide batch service."""
    return _get_batch_svc()


# ── Integration clients ───────────────────────────────────────────────────────

_sheets_client = SheetsClient(document_name=settings.sheets_document_name)


def get_sheets_client() -> SheetsClient:
    """
    Return the process-wide Google Sheets client.

    Returns:
        SheetsClient configured from Settings.
    """
    return _sheets_client


@lru_cache(maxsize=1)
def get_airtable_client() -> AirtableClient:
    """
    Return the process-wide Airtable client.

    Returns:
        AirtableClient configured from Settings.
    """
    return AirtableClient(
        base_id=settings.airtable_base_id or "",
        table_name=settings.airtable_table_name,
        api_key=settings.airtable_api_key or "",
    )
