from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

_engine_kwargs: dict = {"pool_pre_ping": True}
if settings.database_url.startswith("postgresql"):
    connect_args = dict(settings.database_connect_args)
    if not settings.database_pooled:
        # All timestamps are stored and grouped in UTC. (A pooler may refuse startup settings;
        # hosted Postgres such as Neon already runs in UTC.)
        connect_args["server_settings"] = {"timezone": "UTC"}
    _engine_kwargs.update(pool_size=10, max_overflow=20, connect_args=connect_args)

engine = create_async_engine(settings.database_url, **_engine_kwargs)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

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
    async with SessionLocal() as session:
        yield session


async def create_tables() -> None:
    """Hackathon shortcut: create tables on startup. Move to Alembic once the schema settles."""
    from app import models  # noqa: F401  (register models on Base.metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
