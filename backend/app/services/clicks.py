"""Click logging pipeline.

Redirect path (fast):  build a small event dict -> enqueue to Redis (arq) -> return 302
Worker (slow is fine): burst detection -> INSERT click_event -> bump click_count

The raw IP never leaves the request: we hash it immediately (see core/visitor.py),
so neither Redis nor Postgres ever stores an IP address.

If Redis is unavailable we fall back to FastAPI BackgroundTasks (runs in-process
after the response is sent). Slightly less reliable, but the redirect still works.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import BackgroundTasks, Request
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.agents import Agent
from app.core.urls import referrer_domain
from app.core.visitor import visitor_hash
from app.db import SessionLocal
from app.models import ClickEvent, Link
from app.security import client_ip
from app.services import cache

log = logging.getLogger("linkpulse.clicks")
BURST_WINDOW_SECONDS = 10
BURST_LIMIT = 10  # more than this many redirects from one visitor on one link in 10 s = automated


def build_event(request: Request, link_id: int, outcome: str, *, agent: Agent, country: str | None,
                is_bot: bool, bot_reason: str | None, counted: bool = False,
                destination: str | None = None) -> dict:
    now = datetime.now(timezone.utc)
    ua = request.headers.get("user-agent", "")
    referrer = request.headers.get("referer")
    return {
        "link_id": link_id,
        "ts": now.isoformat(),
        "outcome": outcome,
        "source": "qr" if request.query_params.get("src") == "qr" else "link",
        "referrer": referrer[:1000] if referrer else None,
        "referrer_domain": referrer_domain(referrer),
        "device": agent.device,
        "os": agent.os,
        "browser": agent.browser,
        "country": country or "Unknown",
        "visitor_hash": visitor_hash(settings.secret_key, client_ip(request), ua, now.date()),
        "is_bot": is_bot,
        "bot_reason": bot_reason,
        "destination": destination,
        "counted": counted,
    }


async def enqueue(request: Request, event: dict, background: BackgroundTasks) -> None:
    pool = getattr(request.app.state, "arq", None)
    if pool is not None:
        try:
            await pool.enqueue_job("process_click", event)
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("queue unavailable, logging click in-process: %s", exc)
    background.add_task(record_in_new_session, event)


async def record_in_new_session(event: dict) -> None:
    async with SessionLocal() as session:
        await record(session, event)


async def record(session: AsyncSession, event: dict) -> None:
    is_bot, reason = event["is_bot"], event["bot_reason"]
    if event["outcome"] == "redirect" and not is_bot:
        n = await cache.incr_with_ttl(f"burst:{event['link_id']}:{event['visitor_hash']}", BURST_WINDOW_SECONDS)
        if n is not None and n > BURST_LIMIT:
            is_bot, reason = True, "click burst"

    session.add(ClickEvent(
        link_id=event["link_id"], ts=datetime.fromisoformat(event["ts"]), outcome=event["outcome"],
        source=event["source"], referrer=event["referrer"], referrer_domain=event["referrer_domain"],
        device=event["device"], os=event["os"], browser=event["browser"], country=event["country"],
        visitor_hash=event["visitor_hash"], is_bot=is_bot, bot_reason=reason, destination=event["destination"],
    ))
    # Capped links were already counted atomically in the request path.
    if event["outcome"] == "redirect" and not is_bot and not event["counted"]:
        await session.execute(
            update(Link).where(Link.id == event["link_id"])
            .values(click_count=Link.click_count + 1)
            .execution_options(synchronize_session=False))
    await session.commit()
