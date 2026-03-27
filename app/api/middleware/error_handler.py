"""
Global error-handling middleware.

Converts BaseAppError subclasses into consistent JSON responses matching
the portfolio API response envelope:

  {"status": "error", "error": {"code": "...", "message": "...", "context": {}}, "metadata": {...}}

Unhandled exceptions produce a generic 500 response — the real error is
logged with the correlation ID for tracing.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.exceptions import BaseAppError
from app.core.logging_config import get_correlation_id

logger = logging.getLogger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """Convert application exceptions into structured JSON error responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """
        Process each request, catching application errors.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware or route handler.

        Returns:
            The normal response, or a structured JSON error response.
        """
        try:
            return await call_next(request)
        except BaseAppError as exc:
            logger.warning(
                "Application error",
                extra={
                    "error_code": exc.error_code,
                    "status_code": exc.status_code,
                    "message": exc.message,
                    "context": exc.context,
                    "correlation_id": get_correlation_id(),
                },
            )
            return JSONResponse(
                status_code=exc.status_code,
                content=_error_envelope(exc.error_code, exc.message, exc.context),
            )
        except Exception as exc:
            logger.error(
                "Unhandled exception",
                extra={
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "correlation_id": get_correlation_id(),
                },
                exc_info=True,
            )
            return JSONResponse(
                status_code=500,
                content=_error_envelope(
                    "INTERNAL_ERROR",
                    "An unexpected error occurred",
                    {},
                ),
            )


def _error_envelope(error_code: str, message: str, context: dict) -> dict:
    return {
        "status": "error",
        "error": {
            "code": error_code,
            "message": message,
            "context": context,
        },
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "correlation_id": get_correlation_id(),
        },
    }
