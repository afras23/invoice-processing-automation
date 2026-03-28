"""
Pydantic response models for the invoice API.

All endpoints wrap their payload in the portfolio-standard envelope:
  success: {"status": "...", "data": {...}, "metadata": {...}}
  error:   {"status": "error", "error": {...}, "metadata": {...}}
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from app.core.logging_config import get_correlation_id

_T = TypeVar("_T")


class ResponseMetadata(BaseModel):
    """Standard metadata block attached to every response."""

    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 UTC timestamp of the response.",
    )
    correlation_id: str = Field(
        default_factory=get_correlation_id,
        description="Request correlation ID for distributed tracing.",
    )


class SuccessResponse(BaseModel, Generic[_T]):
    """Envelope for successful responses."""

    status: Literal["ok"] = "ok"
    data: _T
    metadata: ResponseMetadata = Field(default_factory=ResponseMetadata)


class ErrorDetail(BaseModel):
    """Structured error payload."""

    code: str = Field(..., description="Machine-readable error code (SCREAMING_SNAKE_CASE).")
    message: str = Field(..., description="Human-readable description of the error.")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional structured context for debugging.",
    )


class ErrorResponse(BaseModel):
    """Envelope for error responses."""

    status: Literal["error"] = "error"
    error: ErrorDetail
    metadata: ResponseMetadata = Field(default_factory=ResponseMetadata)


class HealthResponse(BaseModel):
    """Response body for /api/v1/health."""

    status: Literal["healthy"] = "healthy"
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ReadinessResponse(BaseModel):
    """Response body for /api/v1/health/ready."""

    status: Literal["ready", "degraded"]
    checks: dict[str, str] = Field(
        description="Per-dependency check results ('ok' or error description)."
    )


class MetricsResponse(BaseModel):
    """Response body for /api/v1/metrics."""

    uptime_seconds: float
    ai_model: str
    app_env: str
    integrations: dict[str, str]
    ai_costs: dict[str, Any]
    pipeline: dict[str, Any] = Field(
        default_factory=dict,
        description="Pipeline counters: invoices_processed_today, avg_extraction_accuracy, etc.",
    )
