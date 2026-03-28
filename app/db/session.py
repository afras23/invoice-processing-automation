"""
Async SQLAlchemy session factory.

Creates the engine and session maker from settings.database_url.
When database_url is None (default), the engine is not created and
get_async_session() raises RuntimeError — callers should check
settings.database_url before injecting the session.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_engine() -> AsyncEngine | None:
    """Lazily initialise the async engine from settings."""
    global _engine, _session_factory  # noqa: PLW0603
    if _engine is None and settings.database_url:
        _engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
        logger.info("Database engine created", extra={"url": settings.database_url})
    return _engine


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an AsyncSession.

    Raises:
        RuntimeError: If DATABASE_URL is not configured.
    """
    _get_engine()
    if _session_factory is None:
        raise RuntimeError("Database not configured — set DATABASE_URL to enable persistence.")
    async with _session_factory() as session:
        yield session
