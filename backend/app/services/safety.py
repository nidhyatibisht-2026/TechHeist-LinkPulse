"""Checks that need the network or the database.

SSRF note: whenever the SERVER fetches a user-supplied URL (reachability checks,
health checks), an attacker could point it at internal addresses such as
http://169.254.169.254 (cloud metadata) or http://localhost:6379 (our Redis).
So we resolve the hostname first and refuse to fetch if ANY address is private,
and we never follow redirects automatically (a public URL could redirect inward).
"""
from __future__ import annotations

import asyncio
import logging
import socket

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.urls import domain_suffixes, host_of, is_public_ip
from app.models import BlockedDomain
from app.services import cache

log = logging.getLogger("linkpulse.safety")


async def resolve_public(host: str) -> tuple[bool, str]:
    """(ok, detail). ok=False means: do not fetch this host."""
    try:
        infos = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM), timeout=3)
    except (socket.gaierror, asyncio.TimeoutError, UnicodeError):
        return False, "Domain name does not resolve"
    addresses = {info[4][0] for info in infos}
    if not addresses:
        return False, "Domain name does not resolve"
    private = [a for a in addresses if not is_public_ip(a)]
    if private:
        return False, "Domain resolves to a private network address"
    return True, "ok"


async def check_reachable(url: str) -> tuple[str, str]:
    """Returns (status, detail) where status is ok | broken."""
    host = host_of(url)
    ok, detail = await resolve_public(host)
    if not ok:
        return "broken", detail
    headers = {"User-Agent": "LinkPulse-HealthCheck/1.0 (+link destination monitor)"}
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False, headers=headers) as client:
            resp = await client.head(url)
            if resp.status_code in (403, 405, 501):  # some servers reject HEAD
                resp = await client.get(url)
    except httpx.HTTPError as exc:
        return "broken", f"Could not connect ({exc.__class__.__name__})"
    if resp.status_code >= 400:
        return "broken", f"Destination returned HTTP {resp.status_code}"
    return "ok", f"HTTP {resp.status_code}"


async def safe_browsing_threat(url: str) -> str | None:
    """Google Safe Browsing v4 lookup. Only runs when SAFE_BROWSING_API_KEY is set."""
    if not settings.safe_browsing_key:
        return None
    body = {
        "client": {"clientId": "linkpulse", "clientVersion": "1.0"},
        "threatInfo": {
            "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"],
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": url}],
        },
    }
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            resp = await client.post(
                "https://safebrowsing.googleapis.com/v4/threatMatches:find",
                params={"key": settings.safe_browsing_key}, json=body)
            resp.raise_for_status()
            matches = resp.json().get("matches") or []
    except httpx.HTTPError as exc:
        log.warning("safe browsing lookup failed: %s", exc)
        return None
    return matches[0].get("threatType", "UNSAFE") if matches else None


async def blocked_domain_for(session: AsyncSession, url_or_host: str) -> str | None:
    """Blocklist check: Redis set first (fast path), database as fallback."""
    host = host_of(url_or_host) if "://" in url_or_host else url_or_host.lower()
    suffixes = domain_suffixes(host)
    if not suffixes:
        return None
    cached = await cache.blocklist_match(suffixes)
    if cached is not False:
        return cached
    row = await session.scalar(select(BlockedDomain.domain).where(BlockedDomain.domain.in_(suffixes)).limit(1))
    return row


async def all_blocked_domains(session: AsyncSession) -> set[str]:
    return set((await session.scalars(select(BlockedDomain.domain))).all())
