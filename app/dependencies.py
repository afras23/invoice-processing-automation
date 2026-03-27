"""
FastAPI dependency providers.

All stateful objects (AI client, deduplication store) are constructed once
and injected via Depends(). Tests override these with their own fixtures
rather than patching module-level singletons.
"""

from __future__ import annotations

from functools import lru_cache

import anthropic

from app.config import settings
from app.services.ai.client import AnthropicClient
from app.services.deduplication import DeduplicationStore

# ── Process-wide singletons ───────────────────────────────────────────────────


@lru_cache(maxsize=1)
def get_ai_client() -> AnthropicClient:
    """
    Return the process-wide AI client, creating it on first call.

    Returns:
        AnthropicClient configured from Settings.
    """
    raw_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return AnthropicClient(anthropic_client=raw_client, settings=settings)


# Module-level deduplication store shared across requests in the same process.
_dedup_store = DeduplicationStore()


def get_dedup_store() -> DeduplicationStore:
    """
    Return the process-wide deduplication store.

    Returns:
        DeduplicationStore instance (in-memory, not safe for multi-instance deploys).
    """
    return _dedup_store
