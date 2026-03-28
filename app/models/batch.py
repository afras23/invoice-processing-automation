"""
Pydantic models for batch processing.

BatchJobStatus is the in-memory (and API response) representation of a
multi-document processing job.  BatchDocumentResult captures per-file
outcomes so failures are reported without aborting the whole batch.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BatchDocumentResult(BaseModel):
    """Result for one document in a batch job."""

    filename: str = Field(..., description="Original filename")
    status: Literal["processed", "duplicate", "failed"] = Field(
        ..., description="Processing outcome"
    )
    content_hash: str = Field(default="", description="SHA-256 hash of the document text")
    confidence_score: float | None = Field(
        default=None, description="Confidence score if processed"
    )
    validation_passed: bool | None = Field(default=None, description="Whether validation passed")
    error: str | None = Field(default=None, description="Error message if status is 'failed'")


class BatchJobStatus(BaseModel):
    """
    Full lifecycle state of a batch processing job.

    Created on POST /api/v1/batch and updated as each document is processed.
    Returned verbatim by GET /api/v1/batch/{job_id}.
    """

    job_id: str = Field(..., description="Unique job identifier (UUID)")
    status: Literal["pending", "processing", "completed", "failed"] = Field(
        ..., description="Overall job status"
    )
    total: int = Field(..., description="Total number of documents in this batch")
    processed: int = Field(default=0, description="Documents successfully processed")
    failed: int = Field(default=0, description="Documents that failed processing")
    duplicates: int = Field(default=0, description="Documents skipped as duplicates")
    documents: list[BatchDocumentResult] = Field(
        default_factory=list,
        description="Per-document results, populated as processing completes",
    )
