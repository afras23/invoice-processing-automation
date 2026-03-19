"""
Health and metrics endpoints.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter

from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

_started_at = datetime.now(timezone.utc)


@router.get("/health")
async def health() -> dict:
    """Basic liveness check — confirms the process is running."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/ready")
async def readiness() -> dict:
    """
    Readiness check — confirms the application is configured and ready
    to accept requests.
    """
    checks: dict[str, str] = {}

    if settings.anthropic_api_key:
        checks["ai_provider"] = "ok"
    else:
        checks["ai_provider"] = "error: ANTHROPIC_API_KEY not set"

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ready" if all_ok else "degraded",
        "checks": checks,
    }


@router.get("/metrics")
async def metrics() -> dict:
    """Operational metrics for the running instance."""
    uptime = (datetime.now(timezone.utc) - _started_at).total_seconds()
    return {
        "uptime_seconds": round(uptime, 1),
        "ai_model": settings.ai_model,
        "app_env": settings.app_env,
        "integrations": {
            "slack": "configured" if settings.slack_webhook_url else "not configured",
            "sheets": "configured",
        },
    }
