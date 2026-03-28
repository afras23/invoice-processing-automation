"""
Parametrised extraction tests.

Covers multiple vendor formats, currencies, missing fields, and unusual layouts
by driving the full process_invoice pipeline with a mocked AI client.
"""

from __future__ import annotations

import pytest

from app.services.deduplication import DeduplicationStore
from app.services.extraction_service import process_invoice
from tests.conftest import make_mock_ai_client

# ── Parametrised: vendor formats and currencies ───────────────────────────────


@pytest.mark.parametrize(
    "vendor,invoice_id,date,amount,currency",
    [
        ("Acme Corp", "INV-001", "2026-03-01", 1500.00, "USD"),
        ("Beta Ltd", "REF-20260301", "01/03/2026", 750.50, "GBP"),
        ("Gamma GmbH", "GG-0042", "01 March 2026", 99.99, "EUR"),
        ("Δelta Systems", "INV#2026-004", "2026-03-15", 2500.00, "USD"),
        ("Zeta & Co.", "ZC/2026/005", "March 15, 2026", 500.00, "GBP"),
        ("BIG CORP INTERNATIONAL LLC", "BC-INTL-00001", "2026-03-01", 50000.00, "USD"),
        ("Vendor With Spaces In Name", "INV 010", "2026-03-01", 100.00, "EUR"),
        ("日本企業株式会社", "JP-2026-001", "2026-03-01", 110000.0, "JPY"),
        ("O'Brien & Partners", "OBP/INV/001", "2026-03-01", 3200.00, "GBP"),
        ("Société Générale", "SG-2026-001", "01/03/2026", 890.00, "EUR"),
    ],
)
async def test_extraction_various_vendors_succeed(
    vendor: str,
    invoice_id: str,
    date: str,
    amount: float,
    currency: str,
) -> None:
    """Full pipeline succeeds for a range of vendor names, date formats, and currencies."""
    ai_client = make_mock_ai_client(
        {
            "vendor": vendor,
            "invoice_id": invoice_id,
            "date": date,
            "amount": amount,
            "currency": currency,
        }
    )
    result = await process_invoice(
        b"invoice text",
        filename="test.txt",
        dedup_store=DeduplicationStore(),
        ai_client=ai_client,
    )
    assert result.status == "processed"
    assert result.extracted is not None
    assert result.extracted.vendor == vendor
    assert result.extracted.amount == amount


# ── Missing field permutations ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "missing_field,expected_error_fragment",
    [
        ("vendor", "vendor is missing"),
        ("invoice_id", "invoice_id is missing"),
        ("date", "date is missing"),
        ("amount", "amount is missing"),
    ],
)
async def test_extraction_missing_required_field_fails_validation(
    missing_field: str,
    expected_error_fragment: str,
) -> None:
    """When the AI omits a required field the validation step reports the specific error."""
    base_fields: dict[str, object] = {
        "vendor": "Acme Corp",
        "invoice_id": "INV-001",
        "date": "2026-03-01",
        "amount": 100.0,
    }
    base_fields.pop(missing_field)
    ai_client = make_mock_ai_client(base_fields)  # type: ignore[arg-type]
    result = await process_invoice(
        b"invoice text",
        filename="test.txt",
        dedup_store=DeduplicationStore(),
        ai_client=ai_client,
    )
    assert result.status == "processed"  # pipeline completes, validation flags the error
    assert result.validation is not None
    assert not result.validation.passed
    assert any(expected_error_fragment in err for err in result.validation.errors)


# ── Unusual amount layouts ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "amount,valid",
    [
        (0.01, True),
        (1.00, True),
        (99999.99, True),
        (1_000_000.0, True),
        (0.0, False),
        (-50.0, False),
    ],
)
async def test_extraction_amount_range_validation(amount: float, valid: bool) -> None:
    """Amounts ≤ 0 are rejected; all positive values are accepted."""
    ai_client = make_mock_ai_client(
        {"vendor": "Acme", "invoice_id": "INV-1", "date": "2026-03-01", "amount": amount}
    )
    result = await process_invoice(
        b"invoice text",
        filename="test.txt",
        dedup_store=DeduplicationStore(),
        ai_client=ai_client,
    )
    assert result.status == "processed"
    assert result.validation is not None
    assert result.validation.passed == valid


# ── Date format variety ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "date_str",
    [
        "2026-03-01",
        "01/03/2026",
        "03/01/2026",
        "01-03-2026",
        "01 March 2026",
        "March 01, 2026",
        "01 Mar 2026",
    ],
)
async def test_extraction_recognised_date_formats_pass(date_str: str) -> None:
    """Every supported date format produces a valid extraction."""
    ai_client = make_mock_ai_client(
        {"vendor": "Acme", "invoice_id": "INV-1", "date": date_str, "amount": 100.0}
    )
    result = await process_invoice(
        b"invoice text",
        filename="test.txt",
        dedup_store=DeduplicationStore(),
        ai_client=ai_client,
    )
    assert result.validation is not None
    assert "date" not in " ".join(result.validation.errors)


async def test_extraction_unrecognised_date_fails_validation() -> None:
    """A date string in an unknown format is flagged by validation."""
    ai_client = make_mock_ai_client(
        {"vendor": "Acme", "invoice_id": "INV-1", "date": "not-a-date", "amount": 100.0}
    )
    result = await process_invoice(
        b"invoice text",
        filename="test.txt",
        dedup_store=DeduplicationStore(),
        ai_client=ai_client,
    )
    assert result.validation is not None
    assert not result.validation.passed
    assert any("date" in err for err in result.validation.errors)


# ── Confidence degrades with partial data ─────────────────────────────────────


async def test_extraction_all_v2_fields_gives_high_confidence() -> None:
    """A fully-populated v2 extraction with AI confidence scores achieves a high score."""
    ai_client = make_mock_ai_client(
        {
            "vendor": "Acme Corp",
            "invoice_id": "INV-001",
            "date": "2026-03-01",
            "amount": 1500.0,
            "due_date": "2026-04-01",
            "currency": "GBP",
            "subtotal": 1250.0,
            "tax": 250.0,
            "total": 1500.0,
        },
        prompt_version="v2",
    )
    result = await process_invoice(
        b"invoice text",
        filename="test.txt",
        dedup_store=DeduplicationStore(),
        ai_client=ai_client,
    )
    assert result.confidence is not None
    assert result.confidence.score >= 0.8
