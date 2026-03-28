# ADR 002: Line Item Extraction Approach

**Date:** 2026-03-08
**Status:** Accepted

## Context

Invoice line items are the most structurally variable part of an invoice. Formats range from:
- Simple single-line descriptions with a total
- Tabular layouts with qty × unit price = line total
- Grouped items with subtotals, discounts, and tax rows
- Free-form narrative descriptions with no clear structure

The question was how to extract line items reliably while controlling cost and complexity.

## Decision

Extract line items using the Claude v2 prompt, which requests a structured JSON array. Validate the result with a Pydantic model. Use the v1 prompt (no line items) when cost or latency is the priority.

The v2 prompt explicitly instructs the model to:
1. Extract only actual product/service line items — not subtotal, discount, tax, or payment rows
2. Return `null` for `unit_price` and `quantity` when not stated
3. Use the line total as the canonical amount for each item

Cross-field validation then checks:
```
sum(line_items[*].total) + tax ≈ invoice_total   within £0.02 tolerance
```

If this check fails, the validation score drops to 0.0, lowering confidence and routing the invoice to human review.

## Alternatives Considered

### Regex-based table extraction
Tested on 20 sample invoices. Failure rate was high (>30%) due to inconsistent column alignment in PDFs and free-text descriptions containing numbers. Regex requires per-template rules; AI generalises across formats.

### Separate line-item extraction call
Make one AI call for the header fields and a second for line items. Rejected because it doubles the API cost and latency per invoice. The v2 prompt handles both in a single call.

### Ignore line items entirely
Acceptable for simple invoices, but misses the key validation signal: a discrepancy between the sum of line items and the invoice total is a strong indicator of a corrupt or fraudulent document.

### Extract line items from CSV row-by-row
Only applicable to CSV format. The invoice text is normalised to plain text before AI extraction, so format-specific logic was avoided to keep the AI layer format-agnostic.

## Consequences

**Positive:**
- A single v2 prompt call extracts all fields including line items — no extra API calls
- Cross-field validation catches transcription errors and template mismatches
- `null` for optional sub-fields means Pydantic validation doesn't fail on simple invoices

**Negative:**
- v2 prompt produces a larger response than v1 → ~30% higher token cost per invoice
- Line item extraction accuracy is model-dependent; adversarial or unusual layouts may confuse the model
- The £0.02 tolerance is arbitrary; some legitimate invoices round differently and will fail the check

## Cost Note

Deployments that do not need line items should use `PROMPT_VERSION=v1` to reduce per-invoice cost by approximately 30%. The prompt version is configurable per deployment, not per request, to prevent abuse.
