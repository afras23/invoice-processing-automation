"""
Idempotency tests.

Verifies that submitting the same invoice content multiple times results in
exactly one processed document and subsequent attempts are counted as duplicates.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.batch_service import BatchService
from app.services.deduplication import DeduplicationStore
from app.services.extraction_service import process_invoice
from tests.conftest import make_mock_ai_client

SAMPLE_INVOICE_BYTES = (
    b"INVOICE\nVendor: Acme Corp\nInvoice No: INV-001\nDate: 2026-03-01\nAmount Due: 1500.00\n"
)


# ── Single-document idempotency ───────────────────────────────────────────────


async def test_same_invoice_twice_second_is_duplicate() -> None:
    """Submitting the same bytes twice: first is processed, second is duplicate."""
    ai_client = make_mock_ai_client(
        {"vendor": "Acme", "invoice_id": "INV-1", "date": "2026-03-01", "amount": 1500.0}
    )
    dedup = DeduplicationStore()

    first = await process_invoice(
        SAMPLE_INVOICE_BYTES,
        filename="inv.txt",
        dedup_store=dedup,
        ai_client=ai_client,
    )
    second = await process_invoice(
        SAMPLE_INVOICE_BYTES,
        filename="inv.txt",
        dedup_store=dedup,
        ai_client=ai_client,
    )

    assert first.status == "processed"
    assert second.status == "duplicate"


async def test_same_invoice_three_times_only_one_processed() -> None:
    """Regardless of how many times the same invoice is submitted, only one is processed."""
    ai_client = make_mock_ai_client(
        {"vendor": "Acme", "invoice_id": "INV-1", "date": "2026-03-01", "amount": 1500.0}
    )
    dedup = DeduplicationStore()
    statuses = []

    for _ in range(3):
        result = await process_invoice(
            SAMPLE_INVOICE_BYTES,
            filename="inv.txt",
            dedup_store=dedup,
            ai_client=ai_client,
        )
        statuses.append(result.status)

    assert statuses.count("processed") == 1
    assert statuses.count("duplicate") == 2


async def test_duplicate_has_same_content_hash() -> None:
    """The duplicate result carries the same content_hash as the original."""
    ai_client = make_mock_ai_client(
        {"vendor": "Acme", "invoice_id": "INV-1", "date": "2026-03-01", "amount": 1500.0}
    )
    dedup = DeduplicationStore()

    first = await process_invoice(SAMPLE_INVOICE_BYTES, dedup_store=dedup, ai_client=ai_client)
    second = await process_invoice(SAMPLE_INVOICE_BYTES, dedup_store=dedup, ai_client=ai_client)

    assert first.content_hash == second.content_hash


async def test_different_content_not_flagged_as_duplicate() -> None:
    """Two distinct invoices are both processed independently."""
    ai_client = make_mock_ai_client(
        {"vendor": "Acme", "invoice_id": "INV-1", "date": "2026-03-01", "amount": 100.0}
    )
    dedup = DeduplicationStore()

    first = await process_invoice(b"Invoice A content", dedup_store=dedup, ai_client=ai_client)
    second = await process_invoice(b"Invoice B content", dedup_store=dedup, ai_client=ai_client)

    assert first.status == "processed"
    assert second.status == "processed"
    assert first.content_hash != second.content_hash


# ── Batch idempotency ─────────────────────────────────────────────────────────


async def test_batch_with_duplicate_pair_counts_one_duplicate() -> None:
    """A batch containing two identical documents counts exactly one duplicate."""
    ai_client = make_mock_ai_client(
        {"vendor": "Acme", "invoice_id": "INV-1", "date": "2026-03-01", "amount": 100.0}
    )
    svc = BatchService()
    documents = [
        ("inv_a.txt", SAMPLE_INVOICE_BYTES),
        ("inv_b.txt", SAMPLE_INVOICE_BYTES),  # identical content
    ]
    job = svc.create_job([d[0] for d in documents])
    result = await svc.run(
        job.job_id,
        documents,
        ai_client=ai_client,
        dedup_store=DeduplicationStore(),
    )

    assert result.processed == 1
    assert result.duplicates == 1
    assert result.failed == 0


async def test_batch_idempotency_across_sequential_runs() -> None:
    """Re-running a single-document batch with the same content marks second as duplicate."""
    ai_client = make_mock_ai_client(
        {"vendor": "Acme", "invoice_id": "INV-1", "date": "2026-03-01", "amount": 100.0}
    )
    shared_dedup = DeduplicationStore()
    svc = BatchService()

    job1 = svc.create_job(["inv.txt"])
    result1 = await svc.run(
        job1.job_id,
        [("inv.txt", SAMPLE_INVOICE_BYTES)],
        ai_client=ai_client,
        dedup_store=shared_dedup,
    )

    job2 = svc.create_job(["inv.txt"])
    result2 = await svc.run(
        job2.job_id,
        [("inv.txt", SAMPLE_INVOICE_BYTES)],
        ai_client=ai_client,
        dedup_store=shared_dedup,
    )

    assert result1.processed == 1
    assert result2.duplicates == 1


# ── HTTP-level idempotency ─────────────────────────────────────────────────────


def test_http_batch_same_file_twice_second_is_duplicate(test_client: TestClient) -> None:
    """Uploading the same file in two sequential batch requests: second is duplicate."""
    files = [("files", ("invoice.txt", SAMPLE_INVOICE_BYTES, "text/plain"))]

    resp1 = test_client.post("/api/v1/batch", files=files)
    resp2 = test_client.post("/api/v1/batch", files=files)

    assert resp1.status_code == 202
    assert resp2.status_code == 202

    # First batch: 1 processed; second batch: 1 duplicate
    assert resp1.json()["processed"] == 1
    assert resp2.json()["duplicates"] == 1
