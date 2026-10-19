"""Analytics aggregation. Every number comes from click_events (live data).

Definitions (shown in the UI so nobody has to guess):
  clicks           = redirects by humans (outcome=redirect AND is_bot=false)
  unique visitors  = distinct daily visitor hashes among those clicks
  filtered         = events flagged as bots (with a reason)
  blocked attempts = visits to disabled/expired/full links or wrong passwords
All days are UTC.

Scope: users see their own links; admins see the whole platform. Expired,
disabled and archived links are deliberately NOT filtered out.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, desc, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Campaign, ClickEvent, Link, User
from app.services.links import effective_status

HUMAN = and_(ClickEvent.outcome == "redirect", ClickEvent.is_bot.is_(False))
BLOCKED_OUTCOMES = ("blocked", "expired", "limit", "password_failed")


def _scope(user: User, campaign_id: int | None = None, link_id: int | None = None) -> list:
    conds = []
    if user.role != "admin":
        conds.append(Link.owner_id == user.id)
    if campaign_id is not None:
        conds.append(Link.campaign_id == campaign_id)
    if link_id is not None:
        conds.append(Link.id == link_id)
    return conds


def _events(scope: list, since: datetime, *cols):
    return (select(*cols).select_from(ClickEvent).join(Link, Link.id == ClickEvent.link_id)
            .where(*scope, ClickEvent.ts >= since))


def _sum(cond):
    return func.coalesce(func.sum(case((cond, 1), else_=0)), 0)


def _day_key(value) -> str:
    return str(value)[:10]


async def report(session: AsyncSession, user: User, *, days: int = 30, campaign_id: int | None = None,
                 link_id: int | None = None) -> dict:
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    scope = _scope(user, campaign_id, link_id)

    # ---- totals ----
    t = (await session.execute(_events(
        scope, since,
        _sum(HUMAN),
        func.count(distinct(case((HUMAN, ClickEvent.visitor_hash)))),
        _sum(ClickEvent.is_bot.is_(True)),
        _sum(ClickEvent.outcome.in_(BLOCKED_OUTCOMES)),
        _sum(and_(HUMAN, ClickEvent.source == "qr")),
    ))).one()
    totals = {"clicks": int(t[0]), "unique_visitors": int(t[1]), "filtered_bots": int(t[2]),
              "blocked_attempts": int(t[3]), "qr_scans": int(t[4])}

    # ---- time series (one row per UTC day, gaps filled with zeros) ----
    day = func.date(ClickEvent.ts)
    rows = (await session.execute(_events(
        scope, since, day.label("d"), _sum(HUMAN),
        func.count(distinct(case((HUMAN, ClickEvent.visitor_hash)))),
        _sum(ClickEvent.is_bot.is_(True)),
    ).group_by(day).order_by(day))).all()
    by_day = {_day_key(r[0]): r for r in rows}
    series = []
    for i in range(days):
        d = (since + timedelta(days=i)).date().isoformat()
        r = by_day.get(d)
        series.append({"date": d, "clicks": int(r[1]) if r else 0, "unique": int(r[2]) if r else 0,
                       "bots": int(r[3]) if r else 0})

    # ---- breakdowns ----
    async def breakdown(col, limit: int = 8) -> list[dict]:
        n = func.count(ClickEvent.id)
        q = _events(scope, since, col.label("k"), n.label("n")).where(HUMAN).group_by(col).order_by(desc(n)).limit(limit)
        return [{"name": r[0] or "Unknown", "clicks": int(r[1])} for r in (await session.execute(q)).all()]

    breakdowns = {
        "devices": await breakdown(ClickEvent.device),
        "browsers": await breakdown(ClickEvent.browser),
        "os": await breakdown(ClickEvent.os),
        "countries": await breakdown(ClickEvent.country, 10),
        "referrers": await breakdown(ClickEvent.referrer_domain, 10),
        "sources": await breakdown(ClickEvent.source),
    }
    bot_reasons = [
        {"name": r[0] or "unknown", "count": int(r[1])}
        for r in (await session.execute(
            _events(scope, since, ClickEvent.bot_reason, func.count(ClickEvent.id))
            .where(ClickEvent.is_bot.is_(True)).group_by(ClickEvent.bot_reason)
            .order_by(desc(func.count(ClickEvent.id))))).all()
    ]

    # ---- top links ----
    n = func.count(ClickEvent.id)
    top = (await session.execute(
        _events(scope, since, Link.id, Link.code, Link.title, Link.destination, n.label("n"),
                func.count(distinct(ClickEvent.visitor_hash)))
        .where(HUMAN).group_by(Link.id, Link.code, Link.title, Link.destination).order_by(desc(n)).limit(10))).all()
    top_links = [{"id": r[0], "code": r[1], "title": r[2], "destination": r[3], "clicks": int(r[4]),
                  "unique": int(r[5])} for r in top]

    # ---- campaign performance ----
    camp_clicks = (await session.execute(
        _events(scope, since, Link.campaign_id, func.count(ClickEvent.id), func.count(distinct(ClickEvent.visitor_hash)))
        .where(HUMAN).group_by(Link.campaign_id))).all()
    clicks_by_campaign = {r[0]: (int(r[1]), int(r[2])) for r in camp_clicks}
    camp_links = (await session.execute(
        select(Link.campaign_id, Campaign.name, func.count(Link.id))
        .select_from(Link).outerjoin(Campaign, Campaign.id == Link.campaign_id)
        .where(*scope).group_by(Link.campaign_id, Campaign.name))).all()
    campaigns = sorted(
        [{"id": r[0], "name": r[1] or "No campaign", "links": int(r[2]),
          "clicks": clicks_by_campaign.get(r[0], (0, 0))[0], "unique": clicks_by_campaign.get(r[0], (0, 0))[1]}
         for r in camp_links],
        key=lambda c: c["clicks"], reverse=True)

    # ---- link status counts + alerts ----
    links = (await session.scalars(select(Link).where(*scope))).all()
    status_counts: dict[str, int] = {}
    for link in links:
        s = effective_status(link, now)
        status_counts[s] = status_counts.get(s, 0) + 1

    alerts = await _alerts(session, scope, links, now)

    return {"period_days": days, "since": since.isoformat(), "timezone": "UTC", "totals": totals,
            "series": series, "breakdowns": breakdowns, "bot_reasons": bot_reasons, "top_links": top_links,
            "campaigns": campaigns, "link_status": status_counts, "total_links": len(links), "alerts": alerts}


async def _alerts(session: AsyncSession, scope: list, links: list[Link], now: datetime) -> list[dict]:
    alerts: list[dict] = []

    def add(severity: str, kind: str, link: Link, message: str) -> None:
        alerts.append({"severity": severity, "kind": kind, "link_id": link.id, "code": link.code, "message": message})

    by_id = {l.id: l for l in links}
    for link in links:
        status = effective_status(link, now)
        if status == "active" and link.click_cap and link.click_count >= 0.8 * link.click_cap:
            add("medium", "near_cap", link, f"Used {link.click_count} of {link.click_cap} clicks.")
        if status == "active" and link.expires_at:
            exp = link.expires_at if link.expires_at.tzinfo else link.expires_at.replace(tzinfo=timezone.utc)
            if exp - now <= timedelta(days=3):
                hours = max(1, int((exp - now).total_seconds() // 3600))
                add("low", "expiring", link, f"Expires in about {hours} hours.")
        if link.status not in ("archived", "disabled") and link.health_status == "broken":
            add("high", "broken_destination", link, f"Destination looks broken: {link.health_detail or 'no response'}.")

    day_ago, week_ago = now - timedelta(days=1), now - timedelta(days=8)
    recent = (await session.execute(
        _events(scope, day_ago, ClickEvent.link_id, _sum(HUMAN), _sum(ClickEvent.outcome == "blocked"),
                _sum(ClickEvent.outcome == "password_failed"))
        .group_by(ClickEvent.link_id))).all()
    previous = (await session.execute(
        _events(scope, week_ago, ClickEvent.link_id,
                _sum(and_(HUMAN, ClickEvent.ts < day_ago)),
                _sum(ClickEvent.is_bot.is_(True)), func.count(ClickEvent.id))
        .group_by(ClickEvent.link_id))).all()
    prev = {r[0]: (int(r[1]), int(r[2]), int(r[3])) for r in previous}

    for link_id, human_24h, blocked_24h, pw_failed in recent:
        link = by_id.get(link_id)
        if link is None:
            continue
        human_24h, blocked_24h, pw_failed = int(human_24h), int(blocked_24h), int(pw_failed)
        if blocked_24h >= 5 and link.status == "disabled":
            add("high", "disabled_traffic", link, f"Disabled link was opened {blocked_24h} times in the last 24 hours.")
        if pw_failed >= 10:
            add("high", "password_attempts", link, f"{pw_failed} wrong password attempts in the last 24 hours.")
        prior_human = prev.get(link_id, (0, 0, 0))[0]
        daily_avg = prior_human / 7
        if human_24h >= 20 and human_24h > 3 * max(daily_avg, 1):
            add("medium", "spike", link, f"{human_24h} clicks in 24 hours, about {human_24h / max(daily_avg, 1):.0f}x "
                                         "the usual daily volume.")
    for link_id, (_, bots, total) in prev.items():
        link = by_id.get(link_id)
        if link and total >= 20 and bots / total > 0.5:
            add("low", "bot_heavy", link, f"{bots / total:.0%} of recent traffic was automated and filtered out.")

    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(alerts, key=lambda a: order[a["severity"]])[:50]


async def sparklines(session: AsyncSession, link_ids: list[int], days: int = 14) -> dict[int, list[int]]:
    if not link_ids:
        return {}
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    day = func.date(ClickEvent.ts)
    rows = (await session.execute(
        select(ClickEvent.link_id, day, func.count(ClickEvent.id))
        .where(ClickEvent.link_id.in_(link_ids), ClickEvent.ts >= since, HUMAN)
        .group_by(ClickEvent.link_id, day))).all()
    keys = [(since + timedelta(days=i)).date().isoformat() for i in range(days)]
    grid: dict[int, dict[str, int]] = {lid: {} for lid in link_ids}
    for lid, d, n in rows:
        grid[lid][_day_key(d)] = int(n)
    return {lid: [grid[lid].get(k, 0) for k in keys] for lid in link_ids}


async def recent_events(session: AsyncSession, link_id: int, limit: int = 50) -> list[dict]:
    rows = (await session.scalars(
        select(ClickEvent).where(ClickEvent.link_id == link_id).order_by(desc(ClickEvent.ts)).limit(limit))).all()
    return [{"ts": e.ts, "outcome": e.outcome, "source": e.source, "referrer": e.referrer_domain, "device": e.device,
             "os": e.os, "browser": e.browser, "country": e.country, "is_bot": e.is_bot, "bot_reason": e.bot_reason,
             "destination": e.destination} for e in rows]
