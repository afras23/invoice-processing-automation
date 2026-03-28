"""
Pydantic models for the human review queue.

ReviewQueueItem represents an invoice awaiting human review.
ReviewAction is the request body for the POST /api/v1/review/{id} endpoint.
AuditLogEntry is an immutable record of every review decision.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ReviewQueueItem(BaseModel):
    """
    An invoice queued for human review.

    Added automatically when the pipeline produces a confidence score below
    the configured review threshold, or manually by an operator.
    """

    item_id: str = Field(..., description="Unique review item identifier (UUID)")
    content_hash: str = Field(..., description="SHA-256 hash of the invoice text")
    vendor: str | None = None
    invoice_id: str | None = None
    invoice_date: str | None = None
    amount: float | None = None
    confidence_score: float = Field(
        ..., description="Pipeline confidence score that triggered review"
    )
    status: Literal["pending", "approved", "rejected", "edited"] = Field(
        default="pending", description="Current review status"
    )
    reason: str | None = Field(default=None, description="Reviewer notes or rejection reason")
    queued_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 timestamp when item was queued",
    )
    resolved_at: str | None = Field(
        default=None, description="ISO 8601 timestamp when item was resolved"
    )


class ReviewAction(BaseModel):
    """
    Request body for POST /api/v1/review/{id}.

    Specifies the action to take on a review item plus optional notes.
    """

    action: Literal["approve", "reject", "edit"] = Field(..., description="Review decision")
    notes: str | None = Field(default=None, description="Optional reviewer notes")
    changes: dict[str, object] | None = Field(
        default=None,
        description="Field corrections for 'edit' actions (e.g. {'amount': 1500.0})",
    )


class AuditLogEntry(BaseModel):
    """
    Immutable record of a review action.

    Written once when a reviewer acts on a ReviewQueueItem; never updated.
    """

    entry_id: str = Field(..., description="Unique audit entry identifier (UUID)")
    review_item_id: str = Field(..., description="ID of the review item actioned")
    action: Literal["approve", "reject", "edit"] = Field(..., description="Action taken")
    actor: str = Field(default="operator", description="Who performed the action")
    notes: str | None = None
    changes: dict[str, object] | None = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 timestamp",
    )
