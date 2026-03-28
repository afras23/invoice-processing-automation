"""
Batch invoice processing service.

Processes multiple documents in a single job with per-document error isolation
so that one failed file does not abort the entire batch.

The job store is in-memory (process-scoped dict).  BatchJob ORM rows in
app/db/models.py provide persistent storage for multi-process deployments.

Usage:
    batch_svc = get_batch_service()
    job = batch_svc.create_job(filenames)
    await batch_svc.run(job.job_id, documents, ai_client=..., dedup_store=...)
    status = batch_svc.get_job(job.job_id)
"""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from app.models.batch import BatchDocumentResult, BatchJobStatus
from app.services.ai.client import AnthropicClient
from app.services.ai.prompts import DEFAULT_VERSION
from app.services.deduplication import DeduplicationStore
from app.services.extraction_service import process_invoice

logger = logging.getLogger(__name__)

# (filename, raw_bytes) tuples passed to run()
BatchInput = tuple[str, bytes]


class BatchService:
    """
    Processes a list of documents as a named job and tracks per-document results.

    One instance per process — tests should create their own to avoid
    cross-test state.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, BatchJobStatus] = {}

    def create_job(self, filenames: list[str]) -> BatchJobStatus:
        """
        Initialise a new batch job in "pending" status.

        Args:
            filenames: Display names of the documents in this batch.

        Returns:
            BatchJobStatus with job_id and total set; other counters at zero.
        """
        job = BatchJobStatus(
            job_id=str(uuid4()),
            status="pending",
            total=len(filenames),
        )
        self._jobs[job.job_id] = job
        logger.info(
            "Batch job created",
            extra={"job_id": job.job_id, "total_documents": len(filenames)},
        )
        return job

    def get_job(self, job_id: str) -> BatchJobStatus | None:
        """
        Retrieve the current status of a batch job.

        Args:
            job_id: UUID returned by create_job.

        Returns:
            BatchJobStatus if found, None otherwise.
        """
        return self._jobs.get(job_id)

    async def run(
        self,
        job_id: str,
        documents: list[BatchInput],
        *,
        ai_client: AnthropicClient,
        dedup_store: DeduplicationStore,
        prompt_version: str = DEFAULT_VERSION,
    ) -> BatchJobStatus:
        """
        Process all documents in the batch, isolating failures per document.

        Each document is processed independently — a parse or AI error for one
        file does not abort the remaining files.  Duplicate documents (same
        content hash) are counted but not re-processed.

        Args:
            job_id: ID of the job created by create_job().
            documents: List of (filename, bytes) pairs to process.
            ai_client: Injected AI client with retry and cost tracking.
            dedup_store: Injected deduplication store.
            prompt_version: Prompt version for AI extraction.

        Returns:
            Completed BatchJobStatus with all per-document results populated.

        Raises:
            KeyError: If job_id was not registered via create_job().
        """
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"Batch job '{job_id}' not found")

        job.status = "processing"

        doc_results = await asyncio.gather(
            *[
                self._process_one(
                    filename,
                    content,
                    ai_client=ai_client,
                    dedup_store=dedup_store,
                    prompt_version=prompt_version,
                )
                for filename, content in documents
            ],
            return_exceptions=False,
        )

        for doc_result in doc_results:
            job.documents.append(doc_result)
            if doc_result.status == "processed":
                job.processed += 1
            elif doc_result.status == "failed":
                job.failed += 1
            else:
                job.duplicates += 1

        job.status = "completed"
        logger.info(
            "Batch job completed",
            extra={
                "job_id": job_id,
                "processed": job.processed,
                "failed": job.failed,
                "duplicates": job.duplicates,
            },
        )
        return job

    async def _process_one(
        self,
        filename: str,
        content: bytes,
        *,
        ai_client: AnthropicClient,
        dedup_store: DeduplicationStore,
        prompt_version: str,
    ) -> BatchDocumentResult:
        """
        Process a single document and return its result; never raises.

        Args:
            filename: Display name for log context and result reporting.
            content: Raw document bytes.
            ai_client: AI client (shared across the batch).
            dedup_store: Deduplication store (shared across the batch).
            prompt_version: Prompt version for extraction.

        Returns:
            BatchDocumentResult with status, hash, confidence, and optional error.
        """
        try:
            pipeline_result = await process_invoice(
                content,
                filename=filename,
                dedup_store=dedup_store,
                ai_client=ai_client,
                prompt_version=prompt_version,
            )
            confidence = pipeline_result.confidence.score if pipeline_result.confidence else None
            validation_passed = (
                pipeline_result.validation.passed if pipeline_result.validation else None
            )
            return BatchDocumentResult(
                filename=filename,
                status=pipeline_result.status,
                content_hash=pipeline_result.content_hash,
                confidence_score=confidence,
                validation_passed=validation_passed,
            )
        except Exception as exc:
            logger.warning(
                "Batch document failed",
                extra={"filename": filename, "error": str(exc)},
            )
            return BatchDocumentResult(
                filename=filename,
                status="failed",
                error=str(exc),
            )


# ── Process-level singleton ───────────────────────────────────────────────────

_batch_service = BatchService()


def get_batch_service() -> BatchService:
    """Return the process-wide batch service."""
    return _batch_service
