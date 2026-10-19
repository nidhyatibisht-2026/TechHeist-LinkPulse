"""Redis-backed caches. Every function degrades gracefully: if Redis is missing or
down, callers fall back to the database instead of failing the redirect.

Keys:
  link:{code}         JSON snapshot of a link (or "__missing__" for unknown codes)
  blocklist:domains   SET of blocked domains
  blocklist:loaded    marker so an empty set is not confused with "not loaded"
"""
from __future__ import annotations

import json
import logging

from app.config import settings

log = logging.getLogger("linkpulse.cache")
MISSING = "__missing__"
_redis = None


def get_redis():
    global _redis
    if not settings.redis_url:
        return None
    if _redis is None:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(settings.redis_url, decode_responses=True,
                                   socket_timeout=0.5, socket_connect_timeout=0.5)
    return _redis


async def get_link(code: str) -> dict | str | None:
    """Returns a snapshot dict, MISSING (known not to exist) or None (not cached)."""
    r = get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(f"link:{code}")
    except Exception as exc:  # noqa: BLE001
        log.warning("cache get failed: %s", exc)
        return None
    if raw is None:
        return None
    return MISSING if raw == MISSING else json.loads(raw)


async def set_link(code: str, snapshot: dict | None) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        if snapshot is None:
            # Negative cache: protects the DB from people scanning random codes.
            await r.set(f"link:{code}", MISSING, ex=60)
        else:
            await r.set(f"link:{code}", json.dumps(snapshot), ex=settings.link_cache_ttl)
    except Exception as exc:  # noqa: BLE001
        log.warning("cache set failed: %s", exc)


async def invalidate_link(code: str) -> None:
    """Call on EVERY write to a link. This is what makes admin takedowns immediate."""
    r = get_redis()
    if r is None:
        return
    try:
        await r.delete(f"link:{code}")
    except Exception as exc:  # noqa: BLE001
        log.error("cache invalidation failed for %s: %s", code, exc)


async def blocklist_load(domains: list[str]) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        async with r.pipeline(transaction=True) as pipe:
            pipe.delete("blocklist:domains")
            if domains:
                pipe.sadd("blocklist:domains", *domains)
            pipe.set("blocklist:loaded", "1")
            await pipe.execute()
    except Exception as exc:  # noqa: BLE001
        log.warning("blocklist load failed: %s", exc)


async def blocklist_change(add: str | None = None, remove: str | None = None) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        if add:
            await r.sadd("blocklist:domains", add)
        if remove:
            await r.srem("blocklist:domains", remove)
    except Exception as exc:  # noqa: BLE001
        log.warning("blocklist update failed: %s", exc)


async def blocklist_match(suffixes: list[str]) -> str | None | bool:
    """Returns the matching domain, None if not blocked, or False if the cache can't answer."""
    r = get_redis()
    if r is None or not suffixes:
        return False if r is None else None
    try:
        async with r.pipeline(transaction=False) as pipe:
            pipe.get("blocklist:loaded")
            for s in suffixes:
                pipe.sismember("blocklist:domains", s)
            results = await pipe.execute()
    except Exception as exc:  # noqa: BLE001
        log.warning("blocklist check failed: %s", exc)
        return False
    if not results[0]:
        return False
    for suffix, hit in zip(suffixes, results[1:]):
        if hit:
            return suffix
    return None


async def incr_with_ttl(key: str, ttl_seconds: int) -> int | None:
    r = get_redis()
    if r is None:
        return None
    try:
        count = int(await r.incr(key))
        if count == 1:
            await r.expire(key, ttl_seconds)
        return count
    except Exception:  # noqa: BLE001
        return None
