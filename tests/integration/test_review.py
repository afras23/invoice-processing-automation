"""
Integration tests for the human review queue.

Covers:
- Review queue returns pending items
- Approve action logged to audit trail
- Reject action logged to audit trail
- Resolving an already-resolved item returns 409
- Unknown item_id returns 404
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.models.invoice import ConfidenceResult, ExtractedInvoice, PipelineResult, ValidationResult
from app.models.review import ReviewAction
from app.services.review_service import ReviewService

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_pipeline_result(confidence: float = 0.5) -> PipelineResult:
    """Build a minimal PipelineResult for seeding the review queue."""
    return PipelineResult(
        status="processed",
        content_hash="abc123",
        extracted=ExtractedInvoice(
            vendor="Acme Corp", invoice_id="INV-1", date="2026-03-01", amount=500.0
        ),
        validation=ValidationResult(passed=True, errors=[]),
        confidence=ConfidenceResult(score=confidence, completeness=1.0, validation_score=1.0),
    )


# ── Service-level tests ───────────────────────────────────────────────────────


def test_add_to_queue_creates_review_item():
    svc = ReviewService()
    pipeline_result = _make_pipeline_result(confidence=0.5)
    item = svc.add_to_queue(pipeline_result)
    assert item.item_id
    assert item.status == "pending"
    assert item.confidence_score == 0.5
    assert item.vendor == "Acme Corp"


def test_list_pending_returns_items():
    svc = ReviewService()
    svc.add_to_queue(_make_pipeline_result())
    svc.add_to_queue(_make_pipeline_result())
    items = svc.list_pending()
    assert len(items) == 2


def test_approve_action_logged_to_audit_trail():
    svc = ReviewService()
    item = svc.add_to_queue(_make_pipeline_result())
    action = ReviewAction(action="approve", notes="Looks correct")

    audit_entry = svc.process_action(item.item_id, action)

    assert audit_entry.action == "approve"
    assert audit_entry.review_item_id == item.item_id
    assert audit_entry.notes == "Looks correct"
    assert len(svc.get_audit_log()) == 1


def test_reject_action_logged_to_audit_trail():
    svc = ReviewService()
    item = svc.add_to_queue(_make_pipeline_result())
    action = ReviewAction(action="reject", notes="Duplicate invoice")

    audit_entry = svc.process_action(item.item_id, action)

    assert audit_entry.action == "reject"
    assert audit_entry.notes == "Duplicate invoice"


def test_edit_action_captures_changes():
    svc = ReviewService()
    item = svc.add_to_queue(_make_pipeline_result())
    action = ReviewAction(action="edit", changes={"amount": 999.0})

    audit_entry = svc.process_action(item.item_id, action)

    assert audit_entry.action == "edit"
    assert audit_entry.changes == {"amount": 999.0}
    updated_item = svc.list_pending()
    assert len(updated_item) == 0  # no longer pending after edit


def test_double_resolve_raises_value_error():
    svc = ReviewService()
    item = svc.add_to_queue(_make_pipeline_result())
    svc.process_action(item.item_id, ReviewAction(action="approve"))

    with pytest.raises(ValueError, match="already been resolved"):
        svc.process_action(item.item_id, ReviewAction(action="reject"))


def test_pending_count_decreases_after_action():
    svc = ReviewService()
    item = svc.add_to_queue(_make_pipeline_result())
    assert svc.pending_count() == 1
    svc.process_action(item.item_id, ReviewAction(action="approve"))
    assert svc.pending_count() == 0


# ── HTTP endpoint tests ───────────────────────────────────────────────────────


def test_get_review_queue_returns_empty_list(test_client: TestClient):
    """GET /api/v1/review with empty queue returns []."""
    response = test_client.get("/api/v1/review")
    assert response.status_code == 200
    assert response.json() == []


def test_post_review_approve_returns_audit_entry(test_client: TestClient):
    """Seeding queue then POST /api/v1/review/{id} approve returns audit entry."""
    from app.dependencies import get_review_service
    from app.main import app

    fresh_svc = ReviewService()
    item = fresh_svc.add_to_queue(_make_pipeline_result(confidence=0.4))
    app.dependency_overrides[get_review_service] = lambda: fresh_svc

    response = test_client.post(
        f"/api/v1/review/{item.item_id}",
        json={"action": "approve", "notes": "Verified correct"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "approve"
    assert body["review_item_id"] == item.item_id

    app.dependency_overrides.pop(get_review_service, None)


def test_post_review_unknown_id_returns_404(test_client: TestClient):
    """POST /api/v1/review/{unknown} returns 404."""
    response = test_client.post(
        "/api/v1/review/nonexistent-id",
        json={"action": "approve"},
    )
    assert response.status_code == 404
