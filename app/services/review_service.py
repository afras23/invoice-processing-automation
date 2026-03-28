"""
Human review queue service.

Manages the lifecycle of invoice review items:
  - add_to_queue: enqueue a low-confidence invoice for review
  - list_pending: return paginated pending items
  - process_action: approve / reject / edit an item, log to audit trail

The queue is backed by in-memory dicts for portability.  Wire up the
ReviewItem and AuditEntry ORM models in app/db/models.py for persistent
cross-restart storage.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from app.models.invoice import PipelineResult
from app.models.review import AuditLogEntry, ReviewAction, ReviewQueueItem

logger = logging.getLogger(__name__)


class ReviewService:
    """
    In-memory review queue with full audit trail.

    One instance is created at process start and injected via Depends().
    Tests can create their own fresh instance to avoid cross-test pollution.
    """

    def __init__(self) -> None:
        self._queue: dict[str, ReviewQueueItem] = {}
        self._audit_log: list[AuditLogEntry] = []

    def add_to_queue(self, pipeline_result: PipelineResult) -> ReviewQueueItem:
        """
        Enqueue a pipeline result for human review.

        Args:
            pipeline_result: Completed pipeline result with status "processed".

        Returns:
            The newly created ReviewQueueItem.
        """
        extracted = pipeline_result.extracted
        confidence = pipeline_result.confidence.score if pipeline_result.confidence else 0.0

        review_item = ReviewQueueItem(
            item_id=str(uuid4()),
            content_hash=pipeline_result.content_hash,
            vendor=extracted.vendor if extracted else None,
            invoice_id=extracted.invoice_id if extracted else None,
            invoice_date=extracted.date if extracted else None,
            amount=extracted.amount if extracted else None,
            confidence_score=confidence,
        )
        self._queue[review_item.item_id] = review_item

        logger.info(
            "Invoice added to review queue",
            extra={
                "item_id": review_item.item_id,
                "confidence": confidence,
                "vendor": review_item.vendor,
            },
        )
        return review_item

    def list_pending(self, *, page: int = 1, page_size: int = 20) -> list[ReviewQueueItem]:
        """
        Return a paginated list of all pending review items.

        Args:
            page: 1-based page number.
            page_size: Items per page.

        Returns:
            Slice of pending ReviewQueueItems ordered by queue time (oldest first).
        """
        pending = [item for item in self._queue.values() if item.status == "pending"]
        start = (page - 1) * page_size
        return pending[start : start + page_size]

    def pending_count(self) -> int:
        """Return the total number of pending review items."""
        return sum(1 for item in self._queue.values() if item.status == "pending")

    def process_action(
        self,
        item_id: str,
        action: ReviewAction,
        actor: str = "operator",
    ) -> AuditLogEntry:
        """
        Apply a review action to an item and record it in the audit trail.

        Args:
            item_id: ID of the ReviewQueueItem to act on.
            action: The ReviewAction with action type, notes, and optional changes.
            actor: Identifier of the reviewer (default "operator").

        Returns:
            AuditLogEntry created for this action.

        Raises:
            KeyError: If *item_id* is not found in the queue.
            ValueError: If the item is not in "pending" status.
        """
        review_item = self._queue.get(item_id)
        if review_item is None:
            raise KeyError(f"Review item '{item_id}' not found")
        if review_item.status != "pending":
            raise ValueError(
                f"Review item '{item_id}' has already been resolved (status={review_item.status})"
            )

        status_map: dict[str, str] = {"approve": "approved", "reject": "rejected", "edit": "edited"}
        review_item.status = status_map[action.action]  # type: ignore[assignment]
        review_item.reason = action.notes
        review_item.resolved_at = datetime.now(UTC).isoformat()

        audit_entry = AuditLogEntry(
            entry_id=str(uuid4()),
            review_item_id=item_id,
            action=action.action,
            actor=actor,
            notes=action.notes,
            changes=action.changes,
        )
        self._audit_log.append(audit_entry)

        logger.info(
            "Review action processed",
            extra={
                "item_id": item_id,
                "action": action.action,
                "actor": actor,
            },
        )
        return audit_entry

    def get_audit_log(self) -> list[AuditLogEntry]:
        """Return the full audit trail (all entries, oldest first)."""
        return list(self._audit_log)


# ── Process-level singleton ───────────────────────────────────────────────────

_review_service = ReviewService()


def get_review_service() -> ReviewService:
    """Return the process-wide review service."""
    return _review_service
