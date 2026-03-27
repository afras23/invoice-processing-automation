"""
Request/response logging middleware with correlation ID injection.

Sets a correlation_id context variable for each request (sourced from the
X-Correlation-ID header or generated fresh), then logs method, path, status,
and latency at request completion.
"""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging_config import correlation_id_ctx

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with method, path, status, latency, and correlation ID."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """
        Inject correlation ID and log request outcome.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware or route handler.

        Returns:
            The response with X-Correlation-ID header attached.
        """
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid4())
        correlation_id_ctx.set(correlation_id)

        start_ms = time.monotonic() * 1000

        response = await call_next(request)

        latency_ms = round(time.monotonic() * 1000 - start_ms, 1)

        logger.info(
            "HTTP request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
                "correlation_id": correlation_id,
            },
        )

        response.headers["X-Correlation-ID"] = correlation_id
        return response
