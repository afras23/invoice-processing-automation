# Changelog

All notable changes to the AI Invoice Processing Pipeline.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [1.0.0] — 2026-03-28

### Added

**Core Pipeline**
- Multi-format document parsing: PDF (pdfplumber), CSV (auto-delimiter), image, plain text
- SHA-256 content hashing for deterministic deduplication
- `DeduplicationStore` — in-memory hash store with O(1) lookup
- AI extraction via Anthropic Claude with two prompt versions:
  - v1: vendor, invoice_id, date, amount, currency
  - v2: all v1 fields + line_items, due_date, subtotal, tax, per-field confidence
- Cross-field validation: required fields, amount > 0, date normalisation, line item sum vs. total
- Confidence scoring: `(completeness × 0.6) + (validation × 0.4)`
- Confidence-based routing: score ≥ 0.7 → export; score < 0.7 → human review queue

**AI Client**
- Retry with exponential backoff on transient API errors
- Circuit breaker: opens after N consecutive failures, auto-resets after timeout
- Daily cost cap: new requests refused (not crashed) when `MAX_DAILY_COST_USD` is reached
- Per-call cost tracking: model, tokens_in, tokens_out, cost_usd, latency_ms

**Export**
- Xero CSV Bills import format
- QuickBooks Online CSV import format
- Generic CSV with confidence and validation columns
- Google Sheets async row append

**Human Review Queue**
- Low-confidence invoices queued at `GET /api/v1/review`
- Approve / reject / edit actions
- Immutable audit log with actor, timestamp, and field-level change diffs

**Batch Processing**
- `POST /api/v1/batch` — concurrent processing via `asyncio.gather`
- Per-document error isolation: one failure does not abort the batch
- Batch result includes per-document status, confidence, error, and job_id

**Observability**
- Structured JSON logging with `correlation_id` per request
- `GET /api/v1/metrics` — daily cost, call count, utilisation, circuit breaker state
- `GET /api/v1/health` — liveness
- `GET /api/v1/health/ready` — AI provider + database readiness

**Infrastructure**
- FastAPI with async throughout
- Pydantic v2 models at all data boundaries
- PostgreSQL + SQLAlchemy 2.0 async ORM
- Alembic migrations
- Multi-stage Docker build, non-root user, HEALTHCHECK
- `docker-compose.yml` with app + PostgreSQL health checks
- GitHub Actions CI: ruff + mypy + pytest with real PostgreSQL
- Pre-commit hooks: ruff + mypy

**Testing**
- 312 tests total
- Unit: extraction, validation, confidence, deduplication, export formats, currency normalisation
- Integration: pipeline end-to-end, batch, review queue, health/metrics, error recovery, security, idempotency
- Parametrised: 10 vendor/currency combinations, 17 currency normalisation cases, 7 date formats

**Evaluation**
- 35-case labelled test set in `eval/test_set.jsonl`
- Categories: standard (10), partial (5), multi-currency (5), line-item-heavy (5), edge cases (5), adversarial (5)
- `scripts/evaluate.py` — per-field recall, line-item accuracy, cross-field consistency, cost/latency metrics
- Results output to `eval/results/eval_YYYY-MM-DD_HHMMSS.json`
- `make evaluate`, `make evaluate-v2`, `make evaluate-dry-run`

**Documentation**
- README as portfolio case study with architecture diagram, evaluation results, how-to-run
- `docs/architecture.md` — detailed Mermaid flowchart and component descriptions
- `docs/decisions/001-multi-format-parsing-strategy.md`
- `docs/decisions/002-line-item-extraction-approach.md`
- `docs/decisions/003-export-format-design.md`
- `docs/runbook.md` — health checks, common failures, deployment procedures
- `docs/problem-definition.md` — business context and scope

**Sample Data**
- `tests/fixtures/sample_inputs/standard_invoice.txt` — USD, single line item
- `tests/fixtures/sample_inputs/multi_currency_invoice.txt` — GBP, 3 line items
- `tests/fixtures/sample_inputs/line_items_invoice.txt` — USD, 6 line items with discount
- `tests/fixtures/sample_inputs/adversarial_invoice.txt` — prompt injection attempt for security testing
