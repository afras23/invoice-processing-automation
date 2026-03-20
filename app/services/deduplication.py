"""
Deduplication service.

Uses a SHA-256 hash of normalised input text as the deduplication key.
DeduplicationStore is in-memory; replace with a database-backed
implementation when persistence across restarts is required.
"""

import hashlib
import logging

logger = logging.getLogger(__name__)


def compute_hash(text: str) -> str:
    """
    Produce a stable SHA-256 hash of invoice text.

    Whitespace is normalised before hashing so that minor formatting
    differences in the same document do not produce different hashes.

    Args:
        text: Raw invoice text.

    Returns:
        64-character hex digest.
    """
    normalised = " ".join(text.split())
    return hashlib.sha256(normalised.encode()).hexdigest()


class DeduplicationStore:
    """
    In-memory store of content hashes seen during this process lifetime.

    Not safe for multi-instance deployments — swap the backing set for a
    database table (or Redis SET) in production.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def check_and_add(self, content_hash: str) -> bool:
        """
        Check whether *content_hash* has been seen before and record it.

        Args:
            content_hash: Hash produced by compute_hash().

        Returns:
            True if this hash was already present (duplicate), False if new.
        """
        if content_hash in self._seen:
            logger.info("Duplicate invoice detected", extra={"hash": content_hash[:16]})
            return True

        self._seen.add(content_hash)
        return False

    def clear(self) -> None:
        """Reset the store.  Useful in tests."""
        self._seen.clear()

    def __len__(self) -> int:
        return len(self._seen)


# Module-level singleton used by the HTTP route.
# Tests should instantiate their own DeduplicationStore() directly.
_store = DeduplicationStore()


def get_store() -> DeduplicationStore:
    """Return the process-wide deduplication store."""
    return _store
