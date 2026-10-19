"""Country lookup.

Order: CDN header (free and instant when behind Cloudflare/Vercel) -> local
MaxMind GeoLite2 database (GEOIP_DB_PATH; free account needed to download it)
-> None. No external API calls, so the redirect path never waits on the network.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Mapping

from app.config import settings

log = logging.getLogger("linkpulse.geo")
_HEADERS = ("cf-ipcountry", "x-vercel-ip-country", "cloudfront-viewer-country", "x-country-code")


@lru_cache(maxsize=1)
def _reader():
    if not settings.geoip_db_path:
        return None
    try:
        import geoip2.database

        return geoip2.database.Reader(settings.geoip_db_path)
    except Exception as exc:  # noqa: BLE001
        log.warning("GeoIP database unavailable: %s", exc)
        return None


@lru_cache(maxsize=4096)
def _lookup(ip: str) -> str | None:
    reader = _reader()
    if reader is None:
        return None
    try:
        return reader.country(ip).country.iso_code
    except Exception:  # noqa: BLE001  (private IPs, unknown addresses)
        return None


def country_for(ip: str | None, headers: Mapping[str, str] | None = None) -> str | None:
    if headers:
        for h in _HEADERS:
            v = headers.get(h)
            if v and len(v) == 2 and v.upper() not in ("XX", "T1"):
                return v.upper()
    return _lookup(ip) if ip else None
