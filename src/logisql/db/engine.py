from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from logisql.config import Settings

logger = logging.getLogger(__name__)


def async_database_url(raw_url: str) -> str:
    """Return a SQLAlchemy async URL for Supabase/Postgres or SQLite."""

    url = raw_url.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def _ensure_sqlite_parent(raw_url: str) -> None:
    if not raw_url.startswith("sqlite"):
        return
    url = make_url(raw_url)
    database = url.database
    if not database or database == ":memory:":
        return
    Path(database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def create_engine(settings: Settings) -> AsyncEngine:
    """Create the application's async SQLAlchemy engine."""

    url = async_database_url(settings.database_url)
    _ensure_sqlite_parent(url)

    kwargs: dict[str, Any] = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(pool_size=5, max_overflow=10)
        # Supabase's transaction pooler (port 6543) does not support
        # server-side prepared statements. Disable psycopg's prepared cache.
        parsed = make_url(url)
        if parsed.port == 6543:
            kwargs["connect_args"] = {"prepare_threshold": None}

    engine = create_async_engine(url, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
            finally:
                cursor.close()

    return engine


async def ping_database(engine: AsyncEngine) -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # pragma: no cover - depends on external service
        logger.warning("Database health check failed: %s", exc)
        return False


__all__ = ["async_database_url", "create_engine", "ping_database"]
