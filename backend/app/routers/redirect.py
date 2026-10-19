"""GET /{code}: the hot path. Target: no database query at all for a cached, uncapped link.

Per request:
  1. snapshot from Redis (DB on miss)          5. capped + human -> atomic increment (the real cap guard)
  2. bot check, device/OS, country            6. enqueue the click event (async)
  3. blocklist check (Redis set)              7. 302 with Cache-Control: no-store
  4. evaluate() rules (pure function)

Why 302 and not 301: browsers cache 301s permanently. Repeat visits would never
reach us, so clicks would go uncounted and an admin takedown would not stop
people who had visited before.
"""
# No `from __future__ import annotations` here: slowapi's @limiter.limit wraps endpoints, and
# FastAPI would then resolve string annotations against slowapi's globals, not this module's.

import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.core.agents import detect_bot, parse_agent
from app.core.codes import is_lookup_candidate
from app.core.rules import Decision, Visit, evaluate
from app.db import get_session
from app.models import Link
from app.ratelimit import ip_and_path, limiter
from app.security import client_ip, unlock_token, verify_password
from app.services import cache, clicks, pages, safety
from app.services.geo import country_for
from app.services.links import load_snapshot, view_from_snapshot

router = APIRouter(include_in_schema=False)


async def consume_click(session: AsyncSession, link_id: int):
    """Atomic check-and-increment. The database evaluates the WHERE and the SET in one
    statement, so two simultaneous visitors can never both take the last click.
    (Reading the count in Python and then updating would let both through.)"""
    stmt = (update(Link)
            .where(Link.id == link_id, Link.click_cap.is_not(None), Link.click_count < Link.click_cap)
            .values(click_count=Link.click_count + 1)
            .returning(Link.click_count, Link.click_cap)
            .execution_options(synchronize_session=False))
    row = (await session.execute(stmt)).first()
    await session.commit()
    return row


def _redirect(url: str, status: int = 302) -> RedirectResponse:
    return RedirectResponse(url, status_code=status, headers={
        "Cache-Control": "private, no-store, max-age=0",
        "X-Robots-Tag": "noindex",
    })


async def _handle(code: str, request: Request, background: BackgroundTasks, session: AsyncSession,
                  submitted_password: str | None):
    code = code.lower()
    if not is_lookup_candidate(code):
        return pages.message("not_found")
    snap = await load_snapshot(session, code)
    if snap is None:
        return pages.message("not_found")
    view = view_from_snapshot(snap)

    ua = request.headers.get("user-agent")
    is_bot, bot_reason = detect_bot(ua, request.headers)
    agent = parse_agent(ua)
    country = country_for(client_ip(request), request.headers)
    blocked = await safety.blocked_domain_for(session, view.destination)

    password_ok, just_unlocked = False, False
    if view.has_password:
        if submitted_password is not None:
            # bcrypt is deliberately slow (~0.2 s); run it off the event loop.
            password_ok = await run_in_threadpool(verify_password, submitted_password, snap["password_hash"])
            just_unlocked = password_ok
        else:
            cookie = request.cookies.get(f"lp_{code}")
            password_ok = bool(cookie) and hmac.compare_digest(cookie, unlock_token(view.id, snap["password_hash"]))

    decision = evaluate(view, Visit(now=datetime.now(timezone.utc), device=agent.device, os=agent.os,
                                    country=country, password_ok=password_ok, blocked_domain=blocked))

    # A targeting rule may send visitors to a different domain; that one must not be blocklisted either.
    if decision.action == "redirect" and decision.url != view.destination:
        target_blocked = await safety.blocked_domain_for(session, decision.url)
        if target_blocked:
            decision = Decision("blocked", reason=f"{target_blocked} is blocklisted")

    async def log(outcome: str, counted: bool = False, destination: str | None = None) -> None:
        event = clicks.build_event(request, view.id, outcome, agent=agent, country=country, is_bot=is_bot,
                                   bot_reason=bot_reason, counted=counted, destination=destination)
        await clicks.enqueue(request, event, background)

    if decision.action == "password":
        if submitted_password is not None:
            await log("password_failed")
        return pages.password_form(code, request.url.query, error=submitted_password is not None)

    if decision.action == "expired" and decision.url:
        await log("expired", destination=decision.url)
        return _redirect(decision.url)

    if decision.action != "redirect":
        if decision.action in ("blocked", "expired", "limit"):
            await log(decision.action)
        return pages.message(decision.action)

    # Bots on capped links get a title card: they don't learn the destination and can't use up the cap.
    # (Otherwise anyone could bypass a cap just by sending a "WhatsApp" user agent.)
    if is_bot and view.click_cap is not None:
        await log("preview")
        return pages.preview(snap.get("title", ""))

    counted = False
    if not is_bot and view.click_cap is not None:
        row = await consume_click(session, view.id)
        if row is None:
            await cache.invalidate_link(code)  # cached count was stale; refresh it
            await log("limit")
            return pages.message("limit")
        counted = True
        if row[0] >= row[1]:
            await cache.invalidate_link(code)  # that was the last click; next visitor gets the fast "limit" path

    await log("redirect", counted=counted, destination=decision.url)
    # After a POST (password form) use 303 so the browser follows with a GET.
    response = _redirect(decision.url, 303 if submitted_password is not None else 302)
    if just_unlocked:
        response.set_cookie(f"lp_{code}", unlock_token(view.id, snap["password_hash"]), max_age=3600,
                            httponly=True, samesite="lax", secure=settings.base_url.startswith("https"),
                            path=f"/{code}")
    return response


@router.get("/{code}")
async def follow(code: str, request: Request, background: BackgroundTasks,
                 session: AsyncSession = Depends(get_session)):
    return await _handle(code, request, background, session, None)


@router.post("/{code}")
@limiter.limit(settings.password_rate_limit, key_func=ip_and_path)
async def unlock(code: str, request: Request, background: BackgroundTasks, password: str = Form(...),
                 session: AsyncSession = Depends(get_session)):
    return await _handle(code, request, background, session, password)
