"""
Alembic migrations environment.

Configured for async SQLAlchemy with asyncpg (Postgres) or aiosqlite (SQLite).
The database URL is read from the DATABASE_URL environment variable via
app.config.Settings.

To apply migrations:
    alembic upgrade head

To generate a new migration after model changes:
    alembic revision --autogenerate -m "describe the change"
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# Import the Base and all ORM models so Alembic can discover them.
from app.db.base import Base
from app.db.models import (  # noqa: F401 — imported for side-effects (table registration)
    AuditEntry,
    BatchJob,
    LlmCallLog,
    ProcessedInvoice,
    ReviewItem,
)

# ── Alembic config object ─────────────────────────────────────────────────────

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_database_url() -> str:
    """Read the database URL from settings, falling back to alembic.ini."""
    try:
        from app.config import settings  # noqa: PLC0415

        if settings.database_url:
            return settings.database_url
    except Exception:
        pass
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError(
            "DATABASE_URL not set in environment or alembic.ini. "
            "Export DATABASE_URL before running alembic."
        )
    return url


# ── Offline migrations (generate SQL without a live DB) ──────────────────────


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    Emits SQL to stdout rather than connecting to a database.
    Useful for reviewing changes or applying them via a DBA.
    """
    url = _get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online migrations (connect and apply) ────────────────────────────────────


def do_run_migrations(connection: object) -> None:
    """Apply migrations using an existing connection."""
    context.configure(
        connection=connection,  # type: ignore[arg-type]
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations within it."""
    url = _get_database_url()
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    """Entry point for online migration mode."""
    asyncio.run(run_async_migrations())


# ── Dispatch ──────────────────────────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
