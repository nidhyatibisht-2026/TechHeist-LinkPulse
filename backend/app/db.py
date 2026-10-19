from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)

_engine_kwargs: dict[str, Any] = {
    "pool_pre_ping": True,
}

if settings.database_url.startswith("postgresql"):
    connect_args = dict(settings.database_connect_args)
    if not settings.database_pooled:
        # All timestamps are stored and grouped in UTC. (A pooler may refuse startup settings;
        # hosted Postgres such as Neon already runs in UTC.)
        connect_args["server_settings"] = {
            "timezone": "UTC",
            "application_name": "linkpulse_backend",
        }
    _engine_kwargs.update(
        pool_size=15,
        max_overflow=30,
        pool_timeout=30,
        pool_recycle=1800,  # Recycle connections every 30 mins to prevent stale drops
        connect_args=connect_args,
    )

engine = create_async_engine(settings.database_url, **_engine_kwargs)
SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

if settings.database_url.startswith("sqlite"):
    # SQLite (used by the test suite) needs this for SAVEPOINTs to work; recipe from the SQLAlchemy docs.
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_connect(dbapi_connection, _record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine.sync_engine, "begin")
    def _sqlite_begin(conn):
        # IMMEDIATE takes the write lock up front. SQLite allows one writer at a time, and a plain
        # BEGIN can deadlock when two readers both try to upgrade to writers under concurrent tests.
        conn.exec_driver_sql("BEGIN IMMEDIATE")


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an async database session and ensure clean rollback on unhandled errors."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def create_tables() -> None:
    """Create database tables and performance indexes on startup."""
    from app import models  # noqa: F401  (register models on Base.metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema verified and initialized successfully.")


async def check_db_health() -> dict[str, Any]:
    """Execute a lightweight query to verify PostgreSQL/SQLite connectivity and latency."""
    start_time = time.perf_counter()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {"status": "healthy", "latency_ms": latency_ms}
    except Exception as exc:
        logger.error("Database health check failed: %s", exc)
        return {"status": "unhealthy", "error": str(exc)}


async def close_db() -> None:
    """Gracefully dispose of the async connection pool on application shutdown."""
    await engine.dispose()
    logger.info("Database connection pool closed.")
