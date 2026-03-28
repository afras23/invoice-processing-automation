"""
Advanced batch processing tests.

Covers: 10-document batches with mixed success/failure, progress tracking
accuracy, and concurrent batch runs that must not corrupt each other.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

from app.services.ai.client import AICallResult
from app.services.batch_service import BatchService
from app.services.deduplication import DeduplicationStore


def _make_ai_result(vendor: str = "Acme Corp", amount: float = 100.0) -> AICallResult:
    return AICallResult(
        content=json.dumps(
            {"vendor": vendor, "invoice_id": "INV-001", "date": "2026-03-01", "amount": amount}
        ),
        input_tokens=50,
        output_tokens=20,
        cost_usd=0.0002,
        latency_ms=100.0,
        model="claude-test",
        prompt_version="v1",
    )


# ── 10-document batch: 5 valid + 5 invalid ───────────────────────────────────


async def test_ten_document_batch_five_valid_five_failed() -> None:
    """10 documents where every other AI call raises; exactly 5 processed, 5 failed."""
    from app.core.exceptions import ExtractionError

    ai_client = AsyncMock()
    # Alternate success / failure across 10 calls
    ai_client.complete.side_effect = [
        _make_ai_result("Vendor A") if i % 2 == 0 else ExtractionError("AI failed")
        for i in range(10)
    ]

    svc = BatchService()
    documents = [(f"doc_{i}.txt", f"invoice {i}".encode()) for i in range(10)]
    job = svc.create_job([d[0] for d in documents])
    result = await svc.run(
        job.job_id,
        documents,
        ai_client=ai_client,
        dedup_store=DeduplicationStore(),
    )

    assert result.status == "completed"
    assert result.total == 10
    assert result.processed == 5
    assert result.failed == 5
    assert len(result.documents) == 10


async def test_ten_document_batch_all_succeed() -> None:
    """10 unique documents all processed successfully."""
    ai_client = AsyncMock()
    ai_client.complete.return_value = _make_ai_result()
    ai_client.get_metrics.return_value = {"daily_cost_usd": 0.0}

    svc = BatchService()
    documents = [(f"doc_{i}.txt", f"unique invoice content {i}".encode()) for i in range(10)]
    job = svc.create_job([d[0] for d in documents])
    result = await svc.run(
        job.job_id,
        documents,
        ai_client=ai_client,
        dedup_store=DeduplicationStore(),
    )

    assert result.processed == 10
    assert result.failed == 0
    assert result.duplicates == 0


async def test_ten_document_batch_half_duplicate() -> None:
    """10 documents where 5 are duplicates of the first 5; duplicates are counted."""
    ai_client = AsyncMock()
    ai_client.complete.return_value = _make_ai_result()
    ai_client.get_metrics.return_value = {"daily_cost_usd": 0.0}

    svc = BatchService()
    unique_docs = [(f"doc_{i}.txt", f"unique invoice {i}".encode()) for i in range(5)]
    duplicate_docs = [(f"dup_{i}.txt", f"unique invoice {i}".encode()) for i in range(5)]
    all_docs = unique_docs + duplicate_docs

    job = svc.create_job([d[0] for d in all_docs])
    result = await svc.run(
        job.job_id,
        all_docs,
        ai_client=ai_client,
        dedup_store=DeduplicationStore(),
    )

    assert result.processed == 5
    assert result.duplicates == 5
    assert result.failed == 0


# ── Progress tracking accuracy ────────────────────────────────────────────────


async def test_progress_counters_sum_to_total() -> None:
    """After completion, processed + failed + duplicates == total."""
    from app.core.exceptions import ExtractionError

    ai_client = AsyncMock()
    # 3 succeed, 2 fail, 1 duplicate (same content as doc_0)
    ai_client.complete.side_effect = [
        _make_ai_result("V1"),
        _make_ai_result("V2"),
        _make_ai_result("V3"),
        ExtractionError("fail"),
        ExtractionError("fail"),
    ]

    svc = BatchService()
    # doc_5 has same bytes as doc_0 → duplicate
    documents = [
        ("doc_0.txt", b"content_a"),
        ("doc_1.txt", b"content_b"),
        ("doc_2.txt", b"content_c"),
        ("doc_3.txt", b"content_d"),
        ("doc_4.txt", b"content_e"),
        ("doc_5.txt", b"content_a"),  # duplicate of doc_0
    ]
    job = svc.create_job([d[0] for d in documents])
    result = await svc.run(
        job.job_id,
        documents,
        ai_client=ai_client,
        dedup_store=DeduplicationStore(),
    )

    assert result.processed + result.failed + result.duplicates == result.total
    assert result.duplicates == 1


async def test_batch_job_status_transitions_to_completed() -> None:
    """Job status starts as 'pending', transitions to 'completed' after run()."""
    ai_client = AsyncMock()
    ai_client.complete.return_value = _make_ai_result()

    svc = BatchService()
    job = svc.create_job(["doc.txt"])
    assert job.status == "pending"

    result = await svc.run(
        job.job_id,
        [("doc.txt", b"invoice content")],
        ai_client=ai_client,
        dedup_store=DeduplicationStore(),
    )
    assert result.status == "completed"


# ── Concurrent batches ────────────────────────────────────────────────────────


async def test_concurrent_batches_do_not_corrupt_each_other() -> None:
    """Two batches running concurrently each report accurate independent counts."""
    ai_client = AsyncMock()
    ai_client.complete.return_value = _make_ai_result()

    svc = BatchService()
    # Use separate dedup stores so hashes don't collide between batches
    dedup_a = DeduplicationStore()
    dedup_b = DeduplicationStore()

    docs_a = [(f"a_{i}.txt", f"batch A invoice {i}".encode()) for i in range(5)]
    docs_b = [(f"b_{i}.txt", f"batch B invoice {i}".encode()) for i in range(3)]

    job_a = svc.create_job([d[0] for d in docs_a])
    job_b = svc.create_job([d[0] for d in docs_b])

    result_a, result_b = await asyncio.gather(
        svc.run(job_a.job_id, docs_a, ai_client=ai_client, dedup_store=dedup_a),
        svc.run(job_b.job_id, docs_b, ai_client=ai_client, dedup_store=dedup_b),
    )

    assert result_a.total == 5
    assert result_b.total == 3
    # Each job retains its own document list
    assert len(result_a.documents) == 5
    assert len(result_b.documents) == 3
    # Counts are mutually exclusive
    assert result_a.processed + result_a.failed + result_a.duplicates == 5
    assert result_b.processed + result_b.failed + result_b.duplicates == 3


async def test_unknown_job_id_raises_key_error() -> None:
    """run() with an unregistered job_id raises KeyError, not a silent failure."""
    import pytest

    ai_client = AsyncMock()
    svc = BatchService()
    with pytest.raises(KeyError, match="not found"):
        await svc.run(
            "non-existent-uuid",
            [("doc.txt", b"content")],
            ai_client=ai_client,
            dedup_store=DeduplicationStore(),
        )
