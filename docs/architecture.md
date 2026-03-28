# Architecture

## System Overview

The invoice processing pipeline converts unstructured invoice documents into validated, structured data and routes them to accounting systems or a human review queue.

## Full Pipeline Flow

```mermaid
flowchart TD
    subgraph Ingress["API Layer"]
        A1[POST /api/v1/process<br/>Single invoice upload]
        A2[POST /api/v1/batch<br/>Multiple files]
    end

    subgraph Parsing["Document Parsing — services/parsing/"]
        B1[Format Detection<br/>PDF / CSV / Image / Text]
        B2[Text Extraction<br/>pdfplumber / csv / raw]
        B3[SHA-256 Hash<br/>content-addressed identity]
        B4[ParsedDocument<br/>text + hash + format]
    end

    subgraph Dedup["Deduplication — services/deduplication.py"]
        C1{Hash in store?}
        C2[Return status=duplicate]
        C3[Add hash to store]
    end

    subgraph AI["AI Extraction — services/ai/"]
        D1[AnthropicClient<br/>retry + circuit breaker]
        D2[Prompt v1<br/>vendor, id, date, amount]
        D3[Prompt v2<br/>+ line items, due date,<br/>subtotal, tax, confidence]
        D4[ExtractedInvoice<br/>Pydantic-validated output]
    end

    subgraph Validation["Validation — services/validation_service.py"]
        E1[Required fields present]
        E2[Amount > 0]
        E3[Date formats normalised]
        E4[Due date ≥ invoice date]
        E5[Line item sum + tax ≈ total<br/>within £0.02 tolerance]
        E6[Currency → ISO 4217]
    end

    subgraph Scoring["Confidence — services/confidence_service.py"]
        F1["completeness = present_fields / 4"]
        F2["validation_score = 1.0 if passed else 0.0"]
        F3["confidence = completeness×0.6 + validation×0.4"]
    end

    subgraph Routing["Routing"]
        G1{confidence ≥ 0.7?}
    end

    subgraph Export["Export — services/export_service.py"]
        H1[Xero CSV<br/>Bills import format]
        H2[QuickBooks CSV<br/>Online import format]
        H3[Google Sheets<br/>async row append]
        H4[Generic CSV<br/>with confidence column]
    end

    subgraph Review["Human Review — services/review_service.py"]
        I1[Review Queue<br/>GET /api/v1/review]
        I2[Approve / Reject / Edit]
        I3[Immutable Audit Log<br/>actor + timestamp + changes]
    end

    subgraph Observability["Observability"]
        J1[Structured JSON Logs<br/>correlation_id per request]
        J2[GET /api/v1/metrics<br/>cost + latency + counts]
        J3[GET /api/v1/health/ready<br/>AI + DB liveness]
    end

    A1 --> B1
    A2 --> B1
    B1 --> B2 --> B3 --> B4
    B4 --> C1
    C1 -->|yes| C2
    C1 -->|no| C3 --> D1
    D1 --> D2
    D1 --> D3
    D2 --> D4
    D3 --> D4
    D4 --> E1 & E2 & E3 & E4 & E5 & E6
    E1 & E2 & E3 & E4 & E5 & E6 --> F1 --> F2 --> F3
    F3 --> G1
    G1 -->|yes| H1 & H2 & H3 & H4
    G1 -->|no| I1 --> I2 --> I3

    D1 -.->|logs cost + latency| J1
    A1 & A2 -.->|correlation_id| J1
    J1 -.-> J2
    A1 -.-> J3
```

## Component Responsibilities

### API Layer (`app/api/routes/`)

Routes are thin: validate incoming HTTP parameters, call one service, shape the response. No business logic.

| Route file | Responsibility |
|---|---|
| `process.py` | Single-document upload → pipeline |
| `batch.py` | Multi-document upload → batch service |
| `review.py` | Queue list + action endpoint |
| `health.py` | Liveness + readiness + metrics |

### Document Parsing (`app/services/parsing/`)

Format detection is done by inspecting the file extension and MIME type of the uploaded file. Each parser returns a `ParsedDocument`:

```
ParsedDocument
  text: str           — extracted plain text
  content_hash: str   — SHA-256 hex digest
  format: str         — "pdf" | "csv" | "image" | "text"
  filename: str
```

The SHA-256 hash is computed over raw file bytes, not extracted text, ensuring the hash is stable regardless of parser behaviour.

### AI Extraction (`app/services/ai/`)

`AnthropicClient` is a wrapper around the Anthropic SDK with:
- **Retry with exponential backoff** — transient 5xx and rate-limit errors are retried up to `MAX_RETRIES` times
- **Circuit breaker** — opens after `CIRCUIT_BREAKER_THRESHOLD` consecutive failures; all calls immediately raise `CircuitBreakerOpenError` while open
- **Cost tracking** — every call records `tokens_in`, `tokens_out`, `cost_usd`, `latency_ms` and accumulates a daily total; new calls raise `CostLimitExceededError` when `MAX_DAILY_COST_USD` is reached

Two prompt versions:
- **v1** — extracts vendor, invoice_id, date, amount, currency
- **v2** — additionally extracts line_items, due_date, subtotal, tax, per-field confidence scores

### Validation (`app/services/validation_service.py`)

Pure function: `ValidationResult validate(ExtractedInvoice) -> ValidationResult`.

Validation checks run independently; all failures are collected and returned together (not short-circuited). Currency normalisation maps symbols and names to ISO 4217 codes.

### Confidence Scoring (`app/services/confidence_service.py`)

```
completeness     = len(present_required_fields) / 4
                   required: vendor, invoice_id, date, amount

validation_score = 1.0 if all validations passed else 0.0

confidence       = (completeness × 0.6) + (validation_score × 0.4)
```

The 0.6/0.4 split weights completeness (data is there) over validation (data is correct), because partially complete invoices are more recoverable via human review than invoices with corrupted data.

### Export (`app/services/export_service.py`)

All formats are generated as in-memory strings (no temp files). Format selection is via the `format` query parameter on the process endpoint. Google Sheets integration is async and calls the Sheets API directly.

### Review Queue (`app/services/review_service.py`)

Low-confidence invoices are stored in-memory (with DB models for persistence at scale). The queue exposes list and action endpoints. All actions — approve, reject, edit — are appended to an immutable `AuditLog` list. Edits record field-level diffs.

## Data Flow: Single Invoice

```
POST /api/v1/process
  → parse_document(file_bytes)          → ParsedDocument
  → dedup_store.check(content_hash)     → bool
  → ai_client.complete(prompt, text)    → raw JSON
  → validate_invoice(extracted)         → ValidationResult
  → score_confidence(extracted, result) → float
  → route:
      score ≥ 0.7 → export_service.export(extracted, format)
      score < 0.7 → review_service.enqueue(extracted)
  → return PipelineResult
```

## Data Flow: Batch

```
POST /api/v1/batch
  → for each file:
      asyncio.gather(_process_one(file))  ← concurrent, isolated
        → same single-invoice pipeline
        → on any exception: mark document failed, continue
  → return BatchResult(documents=[...])
```

## Dependency Injection

All stateful objects (AI client, dedup store, metrics tracker, review service) are injected via FastAPI `Depends()`. The dependency providers live in `app/dependencies.py`. This enables clean test overrides via `app.dependency_overrides`.

```python
# app/dependencies.py
def get_ai_client() -> AnthropicClient: ...
def get_dedup_store() -> DeduplicationStore: ...
def get_metrics_tracker() -> MetricsTracker: ...
def get_review_service() -> ReviewService: ...
def get_batch_service(...) -> BatchService: ...
```

## Error Hierarchy

```
BaseAppError (status_code, error_code, message, context)
├── PDFParseError
├── ExtractionError
├── ValidationError
├── CircuitBreakerOpenError
└── CostLimitExceededError
```

`process_invoice` catches `PDFParseError` and `ExtractionError` (expected pipeline failures), returns `PipelineResult(status="failed")`. `CircuitBreakerOpenError` and `CostLimitExceededError` propagate to the batch layer where `_process_one` catches all exceptions, marking the document failed without aborting the batch.
