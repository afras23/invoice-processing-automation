# ADR 003: Export Format Design

**Date:** 2026-03-15
**Status:** Accepted

## Context

After successful extraction and validation, invoice data must be pushed into downstream accounting systems. Different clients use different systems. The question was how to support multiple export targets without creating a maintenance burden.

## Decision

Implement format-specific export functions (not classes) in a single `export_service.py` file, one function per format. Format is selected via a `format` query parameter on the process endpoint. All outputs are generated as in-memory strings — no temp files, no disk I/O.

Supported formats:
- **Xero CSV** — Bills import template with required `*` columns (`*ContactName`, `*InvoiceNumber`, `*UnitAmount`, `*AccountCode`, etc.)
- **QuickBooks CSV** — Online bill import format (`Vendor`, `Invoice Number`, `Amount`, `Account`)
- **Google Sheets** — Async append via Sheets API client; returns row number
- **Generic CSV** — Full pipeline output including confidence score, validation status, extraction timestamp

Default: Generic CSV (no accounting system assumption).

## Why Functions, Not Classes

There are exactly 4 export targets. A class hierarchy (`BaseExporter` → `XeroExporter`, etc.) would require a factory, a registration pattern, and abstract methods — all for 4 concrete implementations. The current requirement is met by 4 functions. If a 5th or 6th format is needed, add a function and a match-case branch.

## Alternatives Considered

### Push to accounting system API directly
Xero and QuickBooks both have REST APIs. Rejected for MVP because:
- OAuth flows require per-client credential management (out of scope for v1)
- CSV import is the standard bulk-import path for both systems
- CSV approach works offline and can be reviewed before import

### Plugin/registry pattern
Allows third parties to register custom exporters without modifying the service. Rejected — no current requirement for third-party extension. Can be added when needed.

### Single "normalised" export format
One canonical JSON or CSV that clients transform themselves. Rejected because accounting systems have rigid import templates; any transformation step adds manual work for the finance team, which is what we're trying to eliminate.

### File downloads vs. API responses
Considered returning file download responses (with `Content-Disposition: attachment`) vs. JSON-embedded CSV strings. Decision: return the CSV content as a string within the standard API response envelope. Clients can write the string to a file. This keeps the API response structure uniform.

## Consequences

**Positive:**
- Adding a new export format is a single function + one match-case branch — no existing code changes
- In-memory generation means no cleanup needed; no temp files leaking on error
- Format functions are independently unit-testable

**Negative:**
- Xero and QuickBooks column names are hardcoded from their import templates; if they change their templates, the functions need updating
- Google Sheets integration requires managing a service account credential — operationally more complex than CSV
- No streaming for very large invoice batches; the entire CSV is built in memory before returning
