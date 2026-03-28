"""
Human review queue routes.

Mounted at /api/v1/review:
  GET  /api/v1/review      — paginated list of pending review items
  POST /api/v1/review/{id} — approve / reject / edit a review item
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_review_service
from app.models.review import AuditLogEntry, ReviewAction, ReviewQueueItem
from app.services.review_service import ReviewService

router = APIRouter(tags=["review"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[ReviewQueueItem])
async def list_review_queue(
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    review_svc: ReviewService = Depends(get_review_service),
) -> list[ReviewQueueItem]:
    """
    Return a paginated list of invoices awaiting human review.

    Only items with status "pending" are returned.  Resolved items (approved,
    rejected, edited) are excluded.

    Args:
        page: 1-based page number (default 1).
        page_size: Items per page, 1–100 (default 20).
        review_svc: Injected review service.

    Returns:
        List of ReviewQueueItems, oldest first.
    """
    return review_svc.list_pending(page=page, page_size=page_size)


@router.post("/{item_id}", response_model=AuditLogEntry)
async def process_review(
    item_id: str,
    action: ReviewAction,
    review_svc: ReviewService = Depends(get_review_service),
) -> AuditLogEntry:
    """
    Apply a review action (approve / reject / edit) to a queued invoice.

    The action is recorded in the immutable audit trail regardless of outcome.

    Args:
        item_id: UUID of the ReviewQueueItem to act on.
        action: ReviewAction with action type, optional notes, and field changes.
        review_svc: Injected review service.

    Returns:
        AuditLogEntry created for this action.

    Raises:
        HTTPException 404: If item_id is not found.
        HTTPException 409: If the item has already been resolved.
    """
    try:
        audit_entry = review_svc.process_action(item_id, action)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    logger.info(
        "Review action completed",
        extra={"item_id": item_id, "action": action.action},
    )
    return audit_entry
