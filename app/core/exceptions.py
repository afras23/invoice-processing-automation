"""
Custom exception hierarchy for the invoice processing pipeline.
"""


class InvoiceProcessingError(Exception):
    """Base exception for all invoice processing errors."""


class PDFParseError(InvoiceProcessingError):
    """Raised when a PDF cannot be opened or read."""


class ExtractionError(InvoiceProcessingError):
    """Raised when AI extraction fails or returns data that cannot be parsed."""


class ValidationError(InvoiceProcessingError):
    """Raised when extracted invoice data fails business rule validation."""


class IntegrationError(InvoiceProcessingError):
    """Raised when an external integration (Sheets, Slack) fails."""
