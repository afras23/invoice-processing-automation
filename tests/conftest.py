"""
Shared fixtures for the test suite.
"""

import os

import pytest


# Ensure settings can be instantiated without a real key during tests
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")


@pytest.fixture()
def sample_invoice_text() -> str:
    return (
        "INVOICE\n"
        "Vendor: Acme Corp\n"
        "Invoice No: INV-2026-0042\n"
        "Date: 2026-03-01\n"
        "Amount Due: 1500.00\n"
    )


@pytest.fixture()
def minimal_invoice_text() -> str:
    """Only the amount — vendor, id, and date are absent."""
    return "Total: 99.99"


@pytest.fixture()
def pdf_magic_bytes() -> bytes:
    """Bytes that look like a PDF header (without real PDF content)."""
    return b"%PDF-fake content that is not a real PDF"
