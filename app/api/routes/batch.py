"""
Batch invoice processing routes.

Mounted at /api/v1/batch:
  POST /api/v1/batch              — submit multiple files for processing
  GET  /api/v1/batch/{job_id}     — retrieve job status and per-document results
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.dependencies import get_ai_client, get_batch_service, get_dedup_store, get_metrics_tracker
from app.models.batch import BatchJobStatus
from app.services.ai.client import AnthropicClient
from app.services.batch_service import BatchService
from app.services.deduplication import DeduplicationStore
from app.services.metrics_service import MetricsTracker

router = APIRouter(tags=["batch"])
logger = logging.getLogger(__name__)


@router.post("", response_model=BatchJobStatus, status_code=202)
async def create_batch(
    files: list[UploadFile] | None = None,
    ai_client: AnthropicClient = Depends(get_ai_client),
    dedup_store: DeduplicationStore = Depends(get_dedup_store),
    batch_svc: BatchService = Depends(get_batch_service),
    metrics: MetricsTracker = Depends(get_metrics_tracker),
) -> BatchJobStatus:
    """
    Submit multiple invoice files for batch processing.

    Each document is processed independently — a failure on one file does
    not abort the remaining files.  Duplicate documents (same content hash)
    are skipped and counted but not re-processed.

    Args:
        files: One or more uploaded invoice files.
        ai_client: Injected AI client.
        dedup_store: Injected deduplication store.
        batch_svc: Injected batch service.
        metrics: Injected metrics tracker.

    Returns:
        BatchJobStatus with per-document results (HTTP 202 Accepted).

    Raises:
        HTTPException 400: If no files are provided.
    """
    if not files:  # None or empty list
        raise HTTPException(status_code=400, detail="At least one file is required")

    filenames = [f.filename or f"file_{i}" for i, f in enumerate(files)]
    job = batch_svc.create_job(filenames)

    # Read all bytes before processing (UploadFile cannot be read asynchronously
    # after the route handler yields control, so we materialise all content first).
    documents: list[tuple[str, bytes]] = []
    for uploaded_file, filename in zip(files, filenames, strict=False):
        content = await uploaded_file.read()
        documents.append((filename, content))

    completed_job = await batch_svc.run(
        job.job_id,
        documents,
        ai_client=ai_client,
        dedup_store=dedup_store,
    )

    for doc_result in completed_job.documents:
        if doc_result.status == "processed" and doc_result.confidence_score is not None:
            metrics.record_invoice(doc_result.confidence_score)

    logger.info(
        "Batch job accepted",
        extra={
            "job_id": completed_job.job_id,
            "total": completed_job.total,
            "processed": completed_job.processed,
            "failed": completed_job.failed,
        },
    )
    return completed_job


@router.get("/{job_id}", response_model=BatchJobStatus)
async def get_batch_job(
    job_id: str,
    batch_svc: BatchService = Depends(get_batch_service),
) -> BatchJobStatus:
    """
    Retrieve the status and results of a batch processing job.

    Args:
        job_id: UUID returned by the POST /api/v1/batch endpoint.
        batch_svc: Injected batch service.

    Returns:
        BatchJobStatus with current progress and per-document results.

    Raises:
        HTTPException 404: If the job_id is not found.
    """
    job = batch_svc.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Batch job '{job_id}' not found")
    return job
