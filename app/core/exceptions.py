"""
Custom exception hierarchy for the invoice processing pipeline.

BaseAppError carries an HTTP status code, a machine-readable error_code,
and a free-form context dict so that error handlers can produce consistent
structured responses without re-parsing exception messages.
"""

from typing import Any


class BaseAppError(Exception):
    """
    Root exception for all application errors.

    Args:
        message: Human-readable description of what went wrong.
        status_code: Suggested HTTP status code for API responses.
        error_code: Machine-readable error identifier (SCREAMING_SNAKE_CASE).
        context: Additional structured data for logging and API responses.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 500,
        error_code: str = "INTERNAL_ERROR",
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.context: dict[str, Any] = context or {}


# ── Processing domain ─────────────────────────────────────────────────────────


class InvoiceProcessingError(BaseAppError):
    """Base exception for all invoice processing errors."""

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(
            message, status_code=422, error_code="INVOICE_PROCESSING_ERROR", context=context
        )


class PDFParseError(InvoiceProcessingError):
    """Raised when a PDF cannot be opened or its text extracted."""

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, context=context)
        self.error_code = "PDF_PARSE_ERROR"


class ExtractionError(InvoiceProcessingError):
    """Raised when AI extraction fails or returns data that cannot be parsed."""

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, context=context)
        self.error_code = "EXTRACTION_ERROR"


class ValidationError(InvoiceProcessingError):
    """Raised when extracted invoice data fails business rule validation."""

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, context=context)
        self.error_code = "VALIDATION_ERROR"


class IntegrationError(InvoiceProcessingError):
    """Raised when an external integration (Sheets, Slack) fails."""

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, context=context)
        self.status_code = 502
        self.error_code = "INTEGRATION_ERROR"


# ── AI / cost domain ──────────────────────────────────────────────────────────


class CircuitBreakerOpenError(BaseAppError):
    """
    Raised when the AI circuit breaker is open due to repeated failures.

    The caller should not retry immediately — check context['reset_in_seconds'].
    """

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(
            message,
            status_code=503,
            error_code="CIRCUIT_BREAKER_OPEN",
            context=context,
        )


class CostLimitExceededError(BaseAppError):
    """
    Raised when the daily AI cost limit has been reached.

    Processing is suspended until the limit resets or is raised in config.
    """

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(
            message,
            status_code=429,
            error_code="COST_LIMIT_EXCEEDED",
            context=context,
        )
