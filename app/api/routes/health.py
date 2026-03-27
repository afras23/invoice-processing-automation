"""
Health and metrics endpoints.

Mounted at /api/v1/:
  GET /api/v1/health        — liveness probe
  GET /api/v1/health/ready  — readiness probe (checks AI key configured)
  GET /api/v1/metrics       — operational metrics and AI cost snapshot
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from app.api.schemas.responses import HealthResponse, MetricsResponse, ReadinessResponse
from app.config import settings
from app.dependencies import get_ai_client
from app.services.ai.client import AnthropicClient

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)

_started_at = datetime.now(UTC)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness check — confirms the process is running."""
    return HealthResponse()


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness() -> ReadinessResponse:
    """
    Readiness check — confirms the application is configured and ready.

    Returns:
        ReadinessResponse with status 'ready' or 'degraded' and per-check results.
    """
    dependency_checks: dict[str, str] = {}

    if settings.anthropic_api_key and settings.anthropic_api_key != "test-key":
        dependency_checks["ai_provider"] = "ok"
    else:
        dependency_checks["ai_provider"] = "error: ANTHROPIC_API_KEY not set"

    all_ok = all(check_result == "ok" for check_result in dependency_checks.values())

    return ReadinessResponse(
        status="ready" if all_ok else "degraded",
        checks=dependency_checks,
    )


@router.get("/metrics", response_model=MetricsResponse)
async def metrics(
    ai_client: AnthropicClient = Depends(get_ai_client),
) -> MetricsResponse:
    """
    Operational metrics including AI cost utilisation.

    Returns:
        MetricsResponse with uptime, AI cost snapshot, and integration status.
    """
    uptime_seconds = (datetime.now(UTC) - _started_at).total_seconds()

    return MetricsResponse(
        uptime_seconds=round(uptime_seconds, 1),
        ai_model=settings.ai_model,
        app_env=settings.app_env,
        integrations={
            "slack": "configured" if settings.slack_webhook_url else "not configured",
            "sheets": "configured",
        },
        ai_costs=ai_client.get_metrics(),
    )
