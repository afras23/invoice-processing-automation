"""
Integration tests for the batch processing endpoint and service.

Covers:
- Batch creates job and tracks progress
- Failed document does not abort the rest of the batch
- Duplicate document is skipped (not re-processed)
- Per-document results reported correctly
- GET /api/v1/batch/{job_id} retrieves stored result
- 404 on unknown job ID
"""

from __future__ import annotations

import io
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.core.exceptions import ExtractionError
from app.services.ai.client import AICallResult
from app.services.batch_service import BatchService
from app.services.deduplication import DeduplicationStore

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_upload_file(name: str, content: bytes = b"invoice text") -> tuple:
    """Return a (name, fileobj, content-type) tuple for requests.files."""
    return (name, io.BytesIO(content), "text/plain")


def _ai_result(vendor: str = "Acme Corp") -> AICallResult:
    import json

    return AICallResult(
        content=json.dumps(
            {"vendor": vendor, "invoice_id": "INV-001", "date": "2026-03-01", "amount": 100.0}
        ),
        input_tokens=50,
        output_tokens=20,
        cost_usd=0.0002,
        latency_ms=200.0,
        model="claude-test",
        prompt_version="v1",
    )


# ── Service-level tests ───────────────────────────────────────────────────────


async def test_batch_creates_job_with_correct_total(good_ai_client, dedup_store):
    """Batch job is created with total matching the number of documents."""
    svc = BatchService()
    job = svc.create_job(["a.txt", "b.txt", "c.txt"])
    assert job.total == 3
    assert job.status == "pending"
    assert job.job_id


async def test_batch_tracks_progress_after_run(good_ai_client, dedup_store):
    """After run(), the job shows processed/failed/duplicate counts."""
    svc = BatchService()
    job = svc.create_job(["invoice.txt"])
    completed = await svc.run(
        job.job_id,
        [("invoice.txt", b"invoice content")],
        ai_client=good_ai_client,
        dedup_store=dedup_store,
    )
    assert completed.status == "completed"
    assert completed.processed + completed.failed + completed.duplicates == completed.total
    assert len(completed.documents) == 1


async def test_failed_document_does_not_abort_batch():
    """A document that causes an ExtractionError is marked failed; others continue."""
    # First call succeeds, second raises
    failing_client = AsyncMock()
    import json

    success_result = AICallResult(
        content=json.dumps(
            {"vendor": "Acme", "invoice_id": "INV-1", "date": "2026-03-01", "amount": 99.0}
        ),
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.0001,
        latency_ms=100.0,
        model="test",
        prompt_version="v1",
    )
    failing_client.complete.side_effect = [
        success_result,
        ExtractionError("AI timed out"),
    ]

    svc = BatchService()
    dedup = DeduplicationStore()
    job = svc.create_job(["good.txt", "bad.txt"])
    result = await svc.run(
        job.job_id,
        [("good.txt", b"good invoice"), ("bad.txt", b"bad invoice")],
        ai_client=failing_client,
        dedup_store=dedup,
    )

    assert result.status == "completed"
    assert result.processed == 1
    assert result.failed == 1
    statuses = {d.filename: d.status for d in result.documents}
    assert statuses["good.txt"] == "processed"
    assert statuses["bad.txt"] == "failed"


async def test_duplicate_document_skipped_in_batch(good_ai_client):
    """A document whose content hash was already seen is counted as duplicate."""
    dedup = DeduplicationStore()
    svc = BatchService()

    # First submission processes; second with same content is a duplicate.
    same_content = b"identical invoice text"
    job = svc.create_job(["first.txt", "second.txt"])
    result = await svc.run(
        job.job_id,
        [("first.txt", same_content), ("second.txt", same_content)],
        ai_client=good_ai_client,
        dedup_store=dedup,
    )

    assert result.processed == 1
    assert result.duplicates == 1
    statuses = {d.filename: d.status for d in result.documents}
    assert statuses["first.txt"] == "processed"
    assert statuses["second.txt"] == "duplicate"


# ── HTTP endpoint tests ───────────────────────────────────────────────────────


def test_post_batch_returns_202_with_job_id(test_client: TestClient):
    """POST /api/v1/batch returns 202 with a job_id and document results."""
    response = test_client.post(
        "/api/v1/batch",
        files=[
            ("files", ("invoice1.txt", b"Invoice from Acme Corp", "text/plain")),
            ("files", ("invoice2.txt", b"Invoice from Beta Ltd", "text/plain")),
        ],
    )
    assert response.status_code == 202
    body = response.json()
    assert "job_id" in body
    assert body["total"] == 2
    assert body["status"] == "completed"


def test_get_batch_job_returns_status(test_client: TestClient):
    """GET /api/v1/batch/{job_id} returns the stored job status."""
    post_response = test_client.post(
        "/api/v1/batch",
        files=[("files", ("inv.txt", b"invoice text", "text/plain"))],
    )
    job_id = post_response.json()["job_id"]

    get_response = test_client.get(f"/api/v1/batch/{job_id}")
    assert get_response.status_code == 200
    assert get_response.json()["job_id"] == job_id


def test_get_batch_unknown_job_returns_404(test_client: TestClient):
    """GET /api/v1/batch/{unknown} returns 404."""
    response = test_client.get("/api/v1/batch/nonexistent-job-id")
    assert response.status_code == 404


def test_post_batch_empty_files_returns_400(test_client: TestClient):
    """POST /api/v1/batch with no files returns 400."""
    response = test_client.post("/api/v1/batch", files=[])
    assert response.status_code == 400
