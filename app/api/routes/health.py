"""
Health and metrics endpoints.

Mounted at /api/v1/:
  GET /api/v1/health        — liveness probe
  GET /api/v1/health/ready  — readiness probe (AI key + optional DB)
  GET /api/v1/metrics       — real operational metrics
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from app.api.schemas.responses import HealthResponse, MetricsResponse, ReadinessResponse
from app.config import settings
from app.dependencies import get_ai_client, get_metrics_tracker, get_review_service
from app.services.ai.client import AnthropicClient
from app.services.metrics_service import MetricsTracker
from app.services.review_service import ReviewService

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

    Checks:
    - AI provider: ANTHROPIC_API_KEY is set and non-default
    - Database: DATABASE_URL is configured (optional — reports 'not configured')

    Returns:
        ReadinessResponse with status 'ready' or 'degraded' and per-check results.
    """
    dependency_checks: dict[str, str] = {}

    if settings.anthropic_api_key and settings.anthropic_api_key != "test-key":
        dependency_checks["ai_provider"] = "ok"
    else:
        dependency_checks["ai_provider"] = "error: ANTHROPIC_API_KEY not set"

    if settings.database_url:
        dependency_checks["database"] = await _check_database_connectivity()
    else:
        dependency_checks["database"] = "not configured"

    critical_checks = {k: v for k, v in dependency_checks.items() if k != "database"}
    all_critical_ok = all(v == "ok" for v in critical_checks.values())

    return ReadinessResponse(
        status="ready" if all_critical_ok else "degraded",
        checks=dependency_checks,
    )


@router.get("/metrics", response_model=MetricsResponse)
async def metrics(
    ai_client: AnthropicClient = Depends(get_ai_client),
    metrics_tracker: MetricsTracker = Depends(get_metrics_tracker),
    review_svc: ReviewService = Depends(get_review_service),
) -> MetricsResponse:
    """
    Real operational metrics including AI cost utilisation and pipeline stats.

    Returns:
        MetricsResponse with pipeline counters, AI cost snapshot, and uptime.
    """
    uptime_seconds = (datetime.now(UTC) - _started_at).total_seconds()
    ai_cost_metrics = ai_client.get_metrics()
    pipeline_snapshot = metrics_tracker.snapshot(
        cost_today_usd=ai_cost_metrics["daily_cost_usd"],
        pending_review_count=review_svc.pending_count(),
    )

    return MetricsResponse(
        uptime_seconds=round(uptime_seconds, 1),
        ai_model=settings.ai_model,
        app_env=settings.app_env,
        integrations={
            "slack": "configured" if settings.slack_webhook_url else "not configured",
            "sheets": "configured",
            "airtable": ("configured" if settings.airtable_api_key else "not configured"),
        },
        ai_costs=ai_cost_metrics,
        pipeline=pipeline_snapshot.model_dump(),
    )


# ── private helpers ───────────────────────────────────────────────────────────


async def _check_database_connectivity() -> str:
    """
    Attempt a lightweight DB connectivity check.

    Returns:
        "ok" if a connection succeeds, or an "error: ..." string if it fails.
    """
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(settings.database_url, pool_pre_ping=True)  # type: ignore[arg-type]
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return "ok"
    except Exception as exc:
        return f"error: {exc}"
