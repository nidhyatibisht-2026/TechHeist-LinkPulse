"""Seed realistic demo data.  Usage:  python -m scripts.seed --reset

Creates one link in every interesting state so each feature is demoable:
  active, expired (with and without fallback), click-capped near its limit,
  password-protected, device/OS-targeted, scheduled, paused, admin-disabled,
  plus a traffic spike, filtered bots and a blocklisted domain.
Click events are synthetic but use the same columns real traffic produces.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import insert

from app.core.visitor import visitor_hash
from app.db import Base, SessionLocal, engine
from app.models import BlockedDomain, Campaign, ClickEvent, Link, Tag, TargetRule, User
from app.security import hash_password
from app.services import cache

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("linkpulse.seed")

RNG = random.Random(42)  # deterministic: same data on every reset
NOW = datetime.now(timezone.utc)

DEVICES = [("mobile", 62), ("desktop", 30), ("tablet", 8)]
OS_BY_DEVICE = {
    "mobile": [("android", 70), ("ios", 30)],
    "tablet": [("android", 45), ("ios", 55)],
    "desktop": [("windows", 64), ("macos", 26), ("linux", 10)],
}
BROWSER_BY_OS = {
    "android": [("Chrome", 80), ("Samsung Internet", 15), ("Firefox", 5)],
    "ios": [("Safari", 85), ("Chrome", 15)],
    "windows": [("Chrome", 70), ("Edge", 22), ("Firefox", 8)],
    "macos": [("Safari", 45), ("Chrome", 50), ("Firefox", 5)],
    "linux": [("Chrome", 60), ("Firefox", 40)],
}
COUNTRIES = [("IN", 55), ("US", 14), ("GB", 6), ("AE", 6), ("SG", 4), ("DE", 3), ("CA", 3), ("Unknown", 9)]
REFERRERS = [
    ("Direct", 34), ("instagram.com", 22), ("linkedin.com", 12), ("x.com", 9),
    ("google.com", 8), ("youtube.com", 7), ("facebook.com", 5), ("reddit.com", 3)
]
BOTS = [("link preview fetcher", 60), ("search or AI crawler", 20), ("scripted client", 12), ("click burst", 8)]


def pick(options):
    values, weights = zip(*options)
    return RNG.choices(values, weights=weights)[0]


def make_events(
    link_id: int, start: datetime, end: datetime, per_day: float, *,
    qr_share: float = 0.1, outcome: str = "redirect", bot_share: float = 0.08,
    spike_last_day: int = 0
) -> list[dict]:
    events = []
    visitors = [f"seed-{link_id}-{i}" for i in range(max(10, int(per_day * 6)))]

    def add(ts: datetime) -> None:
        device = pick(DEVICES)
        os_name = pick(OS_BY_DEVICE[device])
        is_bot = RNG.random() < bot_share
        events.append({
            "link_id": link_id,
            "ts": ts,
            "outcome": outcome,
            "source": "qr" if RNG.random() < qr_share else "link",
            "referrer": None,
            "referrer_domain": pick(REFERRERS),
            "device": device,
            "os": os_name,
            "browser": pick(BROWSER_BY_OS[os_name]),
            "country": pick(COUNTRIES),
            "visitor_hash": visitor_hash("seed", RNG.choice(visitors), "ua", ts.date()),
            "is_bot": is_bot,
            "bot_reason": pick(BOTS) if is_bot else None,
            "destination": None,
        })

    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= end:
        weekday_boost = 1.25 if day.weekday() < 5 else 0.8
        for _ in range(max(0, int(RNG.gauss(per_day * weekday_boost, per_day * 0.25)))):
            ts = day + timedelta(seconds=RNG.randint(0, 86399))
            if start <= ts <= end:
                add(ts)
        day += timedelta(days=1)
    
    for _ in range(spike_last_day):
        add(end - timedelta(seconds=RNG.randint(0, 86000)))
    return events


async def main(reset: bool) -> None:
    async with engine.begin() as conn:
        if reset:
            log.info("Resetting database: dropping all existing tables...")
            await conn.run_sync(Base.metadata.drop_all)
        log.info("Creating database tables and indexes...")
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as s:
        log.info("Seeding users, campaigns, tags, and blocklists...")
        admin = User(email="admin@linkpulse.dev", name="Asha (Admin)", role="admin", password_hash=hash_password("Admin@12345"))
        demo = User(email="demo@linkpulse.dev", name="Rohan (Marketing)", password_hash=hash_password("Demo@12345"))
        other = User(email="priya@linkpulse.dev", name="Priya (Ops)", password_hash=hash_password("Priya@12345"))
        s.add_all([admin, demo, other])
        await s.flush()

        diwali = Campaign(owner_id=demo.id, name="Diwali Sale 2026", description="Festive offers across social and email",
                          utm_source="social", utm_medium="paid", utm_campaign="diwali_2026")
        launch = Campaign(owner_id=demo.id, name="App Launch", description="Mobile app install push",
                          utm_source="multi", utm_medium="organic", utm_campaign="app_launch")
        monsoon = Campaign(owner_id=demo.id, name="Monsoon Clearance", description="Ended campaign kept for reporting")
        hiring = Campaign(owner_id=other.id, name="Campus Hiring", description="Placement drive links")
        s.add_all([diwali, launch, monsoon, hiring])

        tags = {n: Tag(owner_id=demo.id, name=n, color=c) for n, c in
                [("instagram", "#C13584"), ("email", "#0B7FB5"), ("print", "#6B4E16"), ("partner", "#1F8A5B")]}
        s.add_all(tags.values())

        s.add_all([
            BlockedDomain(domain="free-giftcards.win", reason="Reported phishing kit", created_by=admin.id),
            BlockedDomain(domain="login-verify-account.com", reason="Credential harvesting", created_by=admin.id)
        ])
        await s.flush()

        def L(code, dest, title, owner=demo, campaign=None, tag_names=(), **kw):
            link = Link(code=code, destination=dest, title=title, owner_id=owner.id,
                        campaign_id=campaign.id if campaign else None, **kw)
            link.tags = [tags[t] for t in tag_names]
            s.add(link)
            return link

        d = lambda n: NOW - timedelta(days=n)  # noqa: E731
        links = {
            "diwali": L("diwali", "https://shop.example.com/diwali?utm_source=social&utm_medium=paid&utm_campaign=diwali_2026",
                        "Diwali landing page", campaign=diwali, tag_names=("instagram",), created_at=d(29)),
            "festive-drop": L("festive-drop", "https://shop.example.com/drops/festive", "Festive drop (trending)",
                              campaign=diwali, tag_names=("instagram", "partner"), created_at=d(12)),
            "early-bird": L("early-bird", "https://shop.example.com/early-bird", "Early-bird coupon (first 100)",
                            campaign=diwali, tag_names=("email",), click_cap=100, created_at=d(6)),
            "get-app": L("get-app", "https://linkpulse-demo.example.com/app", "Get the app (device routing)",
                         campaign=launch, tag_names=("print",), created_at=d(20)),
            "team-offsite": L("team-offsite", "https://docs.example.com/offsite-plan", "Offsite plan (password: offsite26)",
                              password_hash=hash_password("offsite26"), created_at=d(10)),
            "monsoon-sale": L("monsoon-sale", "https://shop.example.com/monsoon", "Monsoon sale (expired, has fallback)",
                              campaign=monsoon, expires_at=d(5), expired_url="https://shop.example.com/sale-ended",
                              created_at=d(28)),
            "rainy-days": L("rainy-days", "https://blog.example.com/rainy-day-picks", "Rainy-day picks (expired)",
                            campaign=monsoon, expires_at=d(9), created_at=d(27)),
            "winter-preview": L("winter-preview", "https://shop.example.com/winter", "Winter preview (scheduled)",
                                starts_at=NOW + timedelta(days=2), created_at=d(1)),
            "old-webinar": L("old-webinar", "https://events.example.com/webinar-replay", "Webinar replay (paused)",
                             status="paused", tag_names=("email",), created_at=d(25)),
            "claim-reward": L("claim-reward", "https://free-giftcards.win/claim", "Reported link (disabled by admin)",
                              owner=other, status="disabled", disabled_reason="Phishing report from 3 users",
                              created_at=d(4)),
            "placements": L("placements", "https://careers.example.com/campus-2026", "Campus placements",
                             owner=other, campaign=hiring, created_at=d(18)),
            "broken-promo": L("broken-promo", "https://shop.example.com/removed-page", "Promo with a dead page",
                              campaign=diwali, health_status="broken", health_detail="Destination returned HTTP 404",
                              health_checked_at=d(0), created_at=d(15)),
        }
        await s.flush()

        s.add_all([
            TargetRule(link_id=links["get-app"].id, kind="os", value="ios", priority=0,
                       destination="https://apps.apple.com/app/id000000000"),
            TargetRule(link_id=links["get-app"].id, kind="os", value="android", priority=0,
                       destination="https://play.google.com/store/apps/details?id=dev.linkpulse.demo"),
        ])

        log.info("Generating synthetic click event streams...")
        events: list[dict] = []
        events += make_events(links["diwali"].id, d(29), NOW, 38, qr_share=0.05)
        events += make_events(links["festive-drop"].id, d(12), NOW, 9, spike_last_day=140)
        events += make_events(links["early-bird"].id, d(6), NOW, 24, bot_share=0.0)
        events += make_events(links["get-app"].id, d(20), NOW, 22, qr_share=0.55)
        events += make_events(links["team-offsite"].id, d(10), NOW, 3)
        events += make_events(links["monsoon-sale"].id, d(28), d(5), 30)
        events += make_events(links["monsoon-sale"].id, d(5), NOW, 4, outcome="expired", bot_share=0.0)
        events += make_events(links["rainy-days"].id, d(27), d(9), 12)
        events += make_events(links["old-webinar"].id, d(25), d(14), 6)
        events += make_events(links["claim-reward"].id, d(4), d(3), 45)
        events += make_events(links["claim-reward"].id, d(3), NOW, 9, outcome="blocked", bot_share=0.0)
        events += make_events(links["placements"].id, d(18), NOW, 14)
        events += make_events(links["broken-promo"].id, d(15), NOW, 5)

        # Keep click_count consistent with the events (human redirects only).
        human = {}
        for e in events:
            if e["outcome"] == "redirect" and not e["is_bot"]:
                human[e["link_id"]] = human.get(e["link_id"], 0) + 1
        for link in links.values():
            link.click_count = human.get(link.id, 0)
            
        # Early-bird: trim so it sits at 92/100, inside the "near cap" alert zone.
        eb = links["early-bird"]
        eb_events = [e for e in events if e["link_id"] == eb.id]
        keep = set(map(id, sorted(eb_events, key=lambda e: e["ts"])[:92]))
        events = [e for e in events if e["link_id"] != eb.id or id(e) in keep]
        eb.click_count = 92

        await s.flush()
        log.info("Inserting %s click events into PostgreSQL...", len(events))
        for i in range(0, len(events), 2000):
            await s.execute(insert(ClickEvent), events[i:i + 2000])
        await s.commit()

    # Clear stale cache entries from previous runs so redirects reflect the fresh data.
    for code in links:
        await cache.invalidate_link(code)
    await cache.blocklist_load(["free-giftcards.win", "login-verify-account.com"])

    log.info("Database seeding completed successfully!")
    print(f"Seeded {len(links)} links and {len(events)} click events.")
    print("Sign in as  admin@linkpulse.dev / Admin@12345   (admin)")
    print("            demo@linkpulse.dev  / Demo@12345    (marketing user)")
    print("            priya@linkpulse.dev / Priya@12345   (second user, for access-control demos)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed LinkPulse PostgreSQL Database")
    parser.add_argument("--reset", action="store_true", help="drop all tables first")
    args = parser.parse_args()
    asyncio.run(main(args.reset))
