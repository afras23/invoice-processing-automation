"""
Invoice repository — data access layer.

Encapsulates all database interactions for invoice records. Currently a
stub; wire up SQLAlchemy AsyncSession when the database schema is ready
(see migrations/ for Alembic setup).

All methods are async to match the async FastAPI request lifecycle.
"""

from __future__ import annotations

import logging

from app.models.invoice import PipelineResult

logger = logging.getLogger(__name__)


class InvoiceRepository:
    """
    Data access object for invoice records.

    Inject this via FastAPI Depends() rather than importing it directly
    so tests can substitute a fake without patching module globals.
    """

    async def save_result(self, pipeline_result: PipelineResult) -> str:
        """
        Persist a processed pipeline result and return its record ID.

        Args:
            pipeline_result: Completed pipeline output with status "processed".

        Returns:
            Unique record ID string assigned by the database.
        """
        raise NotImplementedError("InvoiceRepository.save_result is not yet implemented")

    async def find_by_hash(self, content_hash: str) -> PipelineResult | None:
        """
        Look up a previously processed invoice by its content hash.

        Args:
            content_hash: SHA-256 hex digest of the normalised invoice text.

        Returns:
            Matching PipelineResult, or None if not found.
        """
        raise NotImplementedError("InvoiceRepository.find_by_hash is not yet implemented")
