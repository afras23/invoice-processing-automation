"""
Structured JSON logging configuration.

Sets up a JSON formatter that emits every log record as a single-line
JSON object, including a correlation_id drawn from the request context.
Call configure_logging() once at application startup (in main.py).
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

# Request-scoped correlation ID — set by CorrelationIDMiddleware per request.
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Return the current correlation ID, generating one if absent."""
    value = correlation_id_ctx.get("")
    return value if value else str(uuid4())


class _JSONFormatter(logging.Formatter):
    """Emit each log record as a structured JSON line."""

    # Fields that are part of LogRecord's internal bookkeeping — excluded from
    # the extra dict so they don't pollute the JSON output.
    _INTERNAL_FIELDS = frozenset(
        {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        """Serialise *record* to a JSON string."""
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id_ctx.get(""),
        }

        # Merge any extra={} fields passed at the call site.
        for key, value in record.__dict__.items():
            if key not in self._INTERNAL_FIELDS:
                log_entry[key] = value

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


class _CorrelationIDFilter(logging.Filter):
    """Attach the current correlation_id to every record (for non-JSON handlers)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_ctx.get("")  # type: ignore[attr-defined]
        return True


def configure_logging(level: str = "INFO") -> None:
    """
    Apply JSON structured logging to the root logger.

    Call this once at application startup before any loggers are used.

    Args:
        level: Minimum log level string (e.g. "INFO", "DEBUG").
    """
    handler = logging.StreamHandler()
    handler.setFormatter(_JSONFormatter())
    handler.addFilter(_CorrelationIDFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
