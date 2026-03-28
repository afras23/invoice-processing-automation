"""
In-memory metrics tracker for the invoice processing pipeline.

Tracks per-process counters that are exposed via the /api/v1/metrics endpoint.
Counters reset when the process restarts — use the database (LlmCallLog,
ProcessedInvoice) for persistent reporting.

Usage:
    tracker = get_metrics_tracker()
    tracker.record_invoice(confidence_score=0.95)
    tracker.record_export()
    tracker.snapshot()  # → MetricsSnapshot
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class MetricsSnapshot(BaseModel):
    """Point-in-time snapshot of pipeline metrics for the /metrics endpoint."""

    invoices_processed_today: int = Field(..., description="Invoices processed since process start")
    avg_extraction_accuracy: float = Field(
        ..., description="Mean confidence score across all processed invoices (0.0–1.0)"
    )
    cost_today_usd: float = Field(..., description="Total AI spend since process start in USD")
    pending_review_count: int = Field(..., description="Invoices currently awaiting human review")
    export_count_today: int = Field(..., description="Exports generated since process start")


class MetricsTracker:
    """
    Process-scoped metrics accumulator.

    Not thread-safe (relies on Python GIL); replace with Redis or Prometheus
    counters for multi-process deployments.
    """

    def __init__(self) -> None:
        self._invoices_processed: int = 0
        self._confidence_scores: list[float] = []
        self._exports: int = 0

    def record_invoice(self, confidence_score: float) -> None:
        """
        Record a successfully processed invoice.

        Args:
            confidence_score: Pipeline confidence score for this invoice.
        """
        self._invoices_processed += 1
        self._confidence_scores.append(confidence_score)
        logger.debug(
            "Metrics: invoice recorded",
            extra={"total": self._invoices_processed, "confidence": confidence_score},
        )

    def record_export(self) -> None:
        """Increment the export counter by one."""
        self._exports += 1

    def snapshot(
        self,
        *,
        cost_today_usd: float = 0.0,
        pending_review_count: int = 0,
    ) -> MetricsSnapshot:
        """
        Return a point-in-time snapshot of all tracked metrics.

        Args:
            cost_today_usd: Current daily AI cost from the AnthropicClient.
            pending_review_count: Current size of the review queue.

        Returns:
            MetricsSnapshot ready for the API response.
        """
        avg_accuracy = (
            sum(self._confidence_scores) / len(self._confidence_scores)
            if self._confidence_scores
            else 0.0
        )
        return MetricsSnapshot(
            invoices_processed_today=self._invoices_processed,
            avg_extraction_accuracy=round(avg_accuracy, 4),
            cost_today_usd=round(cost_today_usd, 6),
            pending_review_count=pending_review_count,
            export_count_today=self._exports,
        )


# ── Process-level singleton ───────────────────────────────────────────────────

_tracker = MetricsTracker()


def get_metrics_tracker() -> MetricsTracker:
    """Return the process-wide metrics tracker."""
    return _tracker
