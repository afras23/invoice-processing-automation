# Invoice Processing Pipeline

A backend service that ingests invoice documents, extracts structured fields
via AI, validates and scores the result, and outputs clean structured data
for downstream accounting workflows.

---

## System Overview

This service sits between raw document intake and downstream data consumers
(accounting systems, approval queues, audit logs). It accepts PDF or
plain-text invoice documents over HTTP, runs them through a multi-stage
processing pipeline, and returns a structured result indicating what was
extracted, whether it passed validation, how confident the system is in
the result, and whether the document is a duplicate submission.

It does not make approval decisions itself. It produces structured, scored,
and validated data that a downstream system or human reviewer can act on.

---

## Problem Context

Manually processing invoices requires reading unstructured documents in
inconsistent formats, copying field values into structured systems, and
checking for duplicates and errors. This is slow, error-prone, and
difficult to audit.

Common failure modes in manual pipelines:

- Fields misread or transposed during data entry
- Duplicate invoices processed and paid twice
- No record of which documents were processed or when
- Inconsistent handling of edge cases across team members

Automating extraction introduces its own risks: AI models may produce
plausible-but-wrong output, miss fields silently, or accept malformed data
without flagging it. This system addresses those risks through explicit
validation, confidence scoring, and structured error handling at every
stage.

---

## System Design

### Data Flow

```
POST /upload-invoice
       │
       ▼
┌─────────────────────┐
│     Ingestion       │  PDF (pdfplumber) or raw text
│  ingestion.py       │  Falls back to UTF-8 decode on PDF parse failure
└────────┬────────────┘
         │ normalised text
         ▼
┌─────────────────────┐
│   Deduplication     │  SHA-256 of whitespace-normalised content
│  deduplication.py   │  Returns "duplicate" immediately if seen before
└────────┬────────────┘
         │ new document
         ▼
┌─────────────────────┐
│    Extraction       │  Claude API with strict JSON schema prompt
│  extraction.py      │  Parses JSON response → ExtractedInvoice model
└────────┬────────────┘
         │ ExtractedInvoice (nullable fields)
         ▼
┌─────────────────────┐
│    Validation       │  Deterministic business rules
│  validation.py      │  vendor, invoice_id, date format, amount > 0
└────────┬────────────┘
         │ ValidationResult (passed, errors[])
         ▼
┌─────────────────────┐
│  Confidence Score   │  completeness × 0.6 + validation × 0.4
│  confidence.py      │  Purely derived from observable facts
└────────┬────────────┘
         │ ConfidenceResult (score, completeness, validation_score)
         ▼
┌─────────────────────┐
│      Output         │  PipelineResult (JSON)
│  pipeline.py        │  Includes optional CSV row
└─────────────────────┘
```

### Status Values

Every response has a `status` field:

| Status | Meaning |
|--------|---------|
| `processed` | Pipeline ran to completion. Check `confidence.score` and `validation.passed`. |
| `duplicate` | Content hash matched a previously processed document. Not re-processed. |
| `failed` | A stage raised an unrecoverable error (PDF unreadable, AI unreachable, unparseable response). |

---

## Core Capabilities

**Structured field extraction**

Extracts four fields from invoice text: `vendor`, `invoice_id`, `date`,
`amount`. Fields not found in the document are returned as `null`. The AI
model is given a strict output schema and instructed not to invent values.

**Schema validation**

AI output is parsed with `json.loads` and validated against a Pydantic
model. Fields that do not conform to expected types are rejected before
validation rules run. The AI response is treated as untrusted input.

**Validation rules**

- All four fields must be present and non-null
- `amount` must be greater than zero
- `date` must be parseable in one of seven recognised formats (ISO 8601,
  UK/US slash-separated, long-form month names)

**Confidence scoring**

```
completeness    = fields_present / 4
validation_score = 1.0 if validation.passed else 0.0
score           = (completeness × 0.6) + (validation_score × 0.4)
```

The score is deterministic and reproducible for any given extraction
result. It is not derived from AI self-reported confidence. A fully
complete, valid invoice scores 1.0. An invoice with two missing fields
and a validation failure scores 0.3.

**Duplicate detection**

Input text is normalised (whitespace collapsed) and hashed with SHA-256
before extraction runs. If the hash matches a previously seen document,
the pipeline returns `status: "duplicate"` without calling the AI API.

The deduplication store is in-memory. It persists for the lifetime of the
process. See [Failure Modes](#failure-modes) for implications.

**Structured output**

`PipelineResult` is returned as JSON. A `csv_row` field is also populated:
`[vendor, invoice_id, date, amount, confidence_score, validation_passed]`.

---

## Design Decisions

**Strict validation over permissive acceptance**

The system rejects documents with missing required fields rather than
passing them downstream with gaps. A downstream accounting system
receiving a record with a null vendor or amount has no way to know
whether the field was intentionally absent or a processing error. Explicit
validation with named errors makes the failure visible.

**Confidence scoring is deterministic**

The confidence score is computed from the extraction result and validation
outcome — not from the AI's own self-assessment. This makes scores
reproducible: the same extraction result always produces the same score,
which makes them useful for threshold-based routing or audit.

**No OCR pipeline**

The system uses pdfplumber's text layer extraction. This covers standard
PDF invoices (generated by accounting software, emailed from vendors)
reliably and without additional dependencies. Scanned documents with no
text layer will produce sparse or empty extraction. Adding a full OCR
pipeline significantly increases dependency surface area and processing
time; that trade-off was deferred.

**Deduplication before extraction**

The content hash is computed and checked before the AI API is called.
This prevents redundant API calls on duplicate submissions and avoids
the situation where the same document is inserted into a downstream system
twice due to a retry or duplicate upload.

**Integration failures do not fail the request**

Google Sheets and Slack notifications are post-processing side effects.
If they fail, the pipeline result is still returned. Integration errors
are logged as warnings. The core processing result is not dependent on
external integration availability.

---

## Failure Modes

**Missing fields**

The AI returns `null` for fields it cannot identify. Validation reports
each missing field by name. The confidence score decreases proportionally:
two missing fields out of four reduces completeness to 0.5, lowering the
score by 0.3 regardless of whether validation passes.

**Unrecognisable date**

If the `date` field is present but does not match any of the seven
recognised formats, validation reports it as an error:
`"date '15 March 2026' is not a recognised format"`. The document is not
rejected outright — the full result is still returned — but `validation.passed`
is `false` and the confidence score reflects this.

**Invalid amount**

An extracted amount of zero or below fails validation. This covers cases
where the AI extracts a subtotal, tax amount, or incorrectly interprets a
credit note.

**AI returns invalid JSON**

If the AI response cannot be parsed as JSON, `ExtractionError` is raised.
The pipeline catches this, logs the error, and returns `status: "failed"`.
The content hash is still recorded in the deduplication store to prevent
the same document triggering repeated failed extraction attempts.

**AI API unavailable or rate-limited**

`anthropic.APIError` is caught in the extraction service and wrapped as
`ExtractionError`. The pipeline returns `status: "failed"`. There is no
automatic retry at the pipeline level — retries should be handled by the
caller.

**Duplicate submission**

The content hash matches a previously processed document. The pipeline
returns immediately with `status: "duplicate"` and the `content_hash`.
No extraction is performed. The response is not an error — the caller
can use it to identify the original processing run by hash.

**Unparseable PDF**

pdfplumber failure triggers a UTF-8 text decode fallback. If the bytes
cannot be decoded as text either, `PDFParseError` is raised and the
pipeline returns `status: "failed"`.

---

## Reliability Considerations

**Rejection over silent failure**

Every stage either returns a typed result or raises a named exception.
There is no path where invalid data passes downstream without a visible
signal. The `status` field in every response is always one of three
explicit states.

**Validation is separate from extraction**

The AI extracts fields. A deterministic rule engine validates them. These
are separate stages with separate responsibilities. Validation does not
depend on the AI's interpretation of field quality — it applies fixed
rules regardless of which model produced the extraction.

**Structured logging at every stage**

Each stage logs its outcome with structured context (field names, token
usage, confidence scores, content hash prefix). This makes it possible
to trace a specific document through the pipeline in logs using the
`content_hash`.

**Schema validation on AI output**

The AI response is parsed with `json.loads` before any downstream code
sees it. The result is then validated against a Pydantic model. Unknown
keys are silently dropped; type mismatches raise a validation error before
business rules run.

---

## Running the System

### Prerequisites

- Docker and Docker Compose
- An Anthropic API key

### Setup

```bash
cp .env.example .env
# Set ANTHROPIC_API_KEY in .env
```

### Start

```bash
docker-compose up --build
```

The application starts on port 8000. API documentation is available at
`http://localhost:8000/docs`.

### Verify

```bash
curl http://localhost:8000/health
# {"status":"healthy","timestamp":"..."}

curl http://localhost:8000/health/ready
# {"status":"ready","checks":{"ai_provider":"ok"}}
```

### Process an invoice

```bash
curl -X POST http://localhost:8000/upload-invoice \
  -F "file=@/path/to/invoice.pdf"
```

Response:

```json
{
  "status": "processed",
  "content_hash": "a3f8...",
  "extracted": {
    "vendor": "Acme Ltd",
    "invoice_id": "INV-2026-0042",
    "date": "2026-03-01",
    "amount": 1500.00
  },
  "validation": {
    "passed": true,
    "errors": []
  },
  "confidence": {
    "score": 1.0,
    "completeness": 1.0,
    "validation_score": 1.0
  },
  "csv_row": ["Acme Ltd", "INV-2026-0042", "2026-03-01", "1500.0", "1.0", "YES"]
}
```

### Run tests

```bash
docker-compose run app pytest tests/ -v
```

Or locally:

```bash
pip install -r requirements.txt -r requirements-dev.txt
ANTHROPIC_API_KEY=test pytest tests/ -v
```

---

## Project Structure

```
app/
├── config.py              # Pydantic Settings — all env vars, validated at startup
├── main.py                # FastAPI app, router registration, logging config
├── core/
│   └── exceptions.py      # Exception hierarchy (PDFParseError, ExtractionError, ...)
├── models/
│   └── invoice.py         # All data models: ExtractedInvoice, ValidationResult,
│                          # ConfidenceResult, PipelineResult, Invoice, LineItem
├── services/
│   ├── ingestion.py       # PDF / text → normalised string
│   ├── extraction.py      # Text → ExtractedInvoice via Claude API
│   ├── validation.py      # ExtractedInvoice → ValidationResult (deterministic rules)
│   ├── confidence.py      # ExtractedInvoice + ValidationResult → ConfidenceResult
│   ├── deduplication.py   # SHA-256 hashing + DeduplicationStore
│   └── pipeline.py        # Orchestrates all stages → PipelineResult
├── routes/
│   ├── invoices.py        # POST /upload-invoice
│   └── health.py          # GET /health, /health/ready, /metrics
└── integrations/
    ├── sheets.py          # Google Sheets (optional, skipped if no credentials)
    └── slack.py           # Slack webhook (optional, skipped if not configured)

tests/
├── conftest.py            # Shared fixtures
├── test_ingestion.py      # PDF parsing, text decode, fallback behaviour
├── test_extraction.py     # AI response handling, error cases
├── test_validation.py     # Field validation, date formats, approval threshold
├── test_confidence.py     # Score computation for all field/validation combinations
├── test_deduplication.py  # Hash stability, store behaviour
└── test_pipeline.py       # End-to-end pipeline, duplicate detection, failure paths

prompts/
└── invoice_extraction.txt # System prompt for AI extraction (version this file)
```

---

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | — | API key for the Claude AI provider |
| `AI_MODEL` | No | `claude-3-5-sonnet-20241022` | Model used for extraction |
| `APPROVAL_THRESHOLD` | No | `500.0` | Invoices above this amount require approval |
| `SLACK_WEBHOOK_URL` | No | — | Slack incoming webhook URL |
| `SERVICE_ACCOUNT_FILE` | No | `service_account.json` | Path to Google service account credentials |
| `SHEETS_DOCUMENT_NAME` | No | `Invoices` | Name of the Google Sheets document |
| `APP_ENV` | No | `development` | Environment name, used in logs |

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `fastapi` | HTTP framework |
| `uvicorn` | ASGI server |
| `anthropic` | Claude API client |
| `pdfplumber` | PDF text extraction |
| `pydantic` / `pydantic-settings` | Data validation and settings management |
| `httpx` | Async-compatible HTTP client (Slack integration) |
| `gspread` / `oauth2client` | Google Sheets integration (optional) |
