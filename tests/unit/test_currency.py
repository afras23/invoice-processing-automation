"""
Currency normalisation and handling tests.

Covers GBP, USD, EUR, JPY (zero-decimal), symbol aliases, mixed-currency edge
cases, and unknown currency passthrough.
"""

from __future__ import annotations

import pytest

from app.models.invoice import ExtractedInvoice
from app.services.validation_service import normalise_currency, validate_extracted

# ── Normalisation: primary currencies ─────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        # GBP
        ("GBP", "GBP"),
        ("gbp", "GBP"),
        ("£", "GBP"),
        ("pound", "GBP"),
        # USD
        ("USD", "USD"),
        ("usd", "USD"),
        ("$", "USD"),
        ("us dollar", "USD"),
        # EUR
        ("EUR", "EUR"),
        ("eur", "EUR"),
        ("€", "EUR"),
        ("euro", "EUR"),
        # JPY — no alias, should uppercase
        ("JPY", "JPY"),
        ("jpy", "JPY"),
        # CAD passthrough
        ("CAD", "CAD"),
        ("cad", "CAD"),
        # CHF passthrough
        ("CHF", "CHF"),
    ],
)
def test_normalise_currency_known_codes(raw: str, expected: str) -> None:
    """All known aliases and passthrough codes are normalised correctly."""
    assert normalise_currency(raw) == expected


def test_normalise_currency_none_returns_none() -> None:
    """None input returns None (currency not present in the invoice)."""
    assert normalise_currency(None) is None


def test_normalise_currency_blank_returns_none() -> None:
    """Empty string returns None (falsy guard in normalise_currency)."""
    assert normalise_currency("") is None


def test_normalise_currency_whitespace_returns_empty_string() -> None:
    """Whitespace-only input passes the falsy guard and returns '' after strip+upper."""
    # "   ".strip() == "" which has no alias → returns "".upper() == ""
    assert normalise_currency("   ") == ""


def test_normalise_currency_unknown_uppercased() -> None:
    """An unrecognised currency is uppercased and returned as-is."""
    assert normalise_currency("sek") == "SEK"
    assert normalise_currency("nzd") == "NZD"


# ── GBP in full pipeline ──────────────────────────────────────────────────────


def test_gbp_currency_normalised_in_validation() -> None:
    """validate_extracted converts '£' to 'GBP' in-place."""
    invoice = ExtractedInvoice(
        vendor="Acme", invoice_id="INV-1", date="2026-03-01", amount=250.0, currency="£"
    )
    validate_extracted(invoice)
    assert invoice.currency == "GBP"


# ── JPY: integer amounts ──────────────────────────────────────────────────────


def test_jpy_integer_amount_passes_validation() -> None:
    """JPY invoice with a whole-number amount (no fractional yen) is valid."""
    invoice = ExtractedInvoice(
        vendor="日本企業",
        invoice_id="JP-001",
        date="2026-03-01",
        amount=110000.0,
        currency="JPY",
    )
    result = validate_extracted(invoice)
    assert result.passed
    assert invoice.currency == "JPY"


def test_jpy_currency_not_aliased_passes_through() -> None:
    """'jpy' (lowercase) is returned as 'JPY' since no alias exists."""
    result = normalise_currency("jpy")
    assert result == "JPY"


# ── EUR with tax ──────────────────────────────────────────────────────────────


def test_eur_invoice_with_vat_passes_validation() -> None:
    """A EUR invoice with VAT (tax) correctly summing to total is valid."""
    from app.models.invoice import LineItem

    invoice = ExtractedInvoice(
        vendor="Gamma GmbH",
        invoice_id="DE-2026-001",
        date="2026-03-01",
        amount=1190.0,
        subtotal=1000.0,
        tax=190.0,
        total=1190.0,
        currency="EUR",
        line_items=[LineItem(description="Software", total=1000.0)],
    )
    result = validate_extracted(invoice)
    assert result.passed
    assert invoice.currency == "EUR"


# ── Currency field absent ─────────────────────────────────────────────────────


def test_missing_currency_does_not_fail_validation() -> None:
    """Currency is optional — a missing currency does not cause validation failure."""
    invoice = ExtractedInvoice(
        vendor="Acme", invoice_id="INV-1", date="2026-03-01", amount=100.0, currency=None
    )
    result = validate_extracted(invoice)
    # Validation may fail for other reasons but NOT because currency is absent
    assert not any("currency" in err.lower() for err in result.errors)


# ── Symbol aliases ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "symbol,expected_code",
    [
        ("$", "USD"),
        ("£", "GBP"),
        ("€", "EUR"),
    ],
)
def test_currency_symbols_map_to_iso_codes(symbol: str, expected_code: str) -> None:
    """Currency symbols are correctly resolved to ISO 4217 codes."""
    assert normalise_currency(symbol) == expected_code
