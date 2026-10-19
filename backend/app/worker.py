"""Background worker. Run with:  arq app.worker.WorkerSettings

Jobs:
  process_click       - one per visit, enqueued by the redirect route
  health_check_links  - every 30 minutes: is each active link's destination still up?
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import or_, select

from app.config import settings
from app.db import SessionLocal, create_tables
from app.models import Link
from app.services import clicks
from app.services.safety import check_reachable

log = logging.getLogger("linkpulse.worker")
HEALTH_BATCH = 200


async def process_click(ctx, event: dict) -> None:
    async with SessionLocal() as session:
        await clicks.record(session, event)


async def health_check_links(ctx) -> dict:
    """Checks the links checked longest ago. Results feed the dashboard's 'broken destination' alerts."""
    stale_before = datetime.now(timezone.utc) - timedelta(minutes=25)
    async with SessionLocal() as session:
        links = (await session.scalars(
            select(Link).where(Link.status == "active",
                               or_(Link.health_checked_at.is_(None), Link.health_checked_at < stale_before))
            .order_by(Link.health_checked_at.asc().nulls_first()).limit(HEALTH_BATCH))).all()
        sem = asyncio.Semaphore(10)

        async def check(link: Link):
            async with sem:
                return link, await check_reachable(link.destination)

        results = await asyncio.gather(*(check(l) for l in links), return_exceptions=True)
        broken = 0
        for r in results:
            if isinstance(r, Exception):
                continue
            link, (status, detail) = r
            link.health_status, link.health_detail = status, detail
            link.health_checked_at = datetime.now(timezone.utc)
            broken += status == "broken"
        await session.commit()
    log.info("health check: %s links, %s broken", len(links), broken)
    return {"checked": len(links), "broken": broken}


async def startup(ctx) -> None:
    if settings.auto_create_tables:
        await create_tables()


class WorkerSettings:
    functions = [process_click]
    cron_jobs = [cron(health_check_links, minute={0, 30}, run_at_startup=True)]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379/0")
    max_jobs = 50
    keep_result = 0  # click jobs don't need stored results
