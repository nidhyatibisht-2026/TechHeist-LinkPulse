"""All configuration comes from environment variables (see .env.example)."""
from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:  # load backend/.env in local development if python-dotenv is installed
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _db_url(raw: str) -> tuple[str, dict, bool]:
    """Return (SQLAlchemy URL, asyncpg connect args, behind a PgBouncer-style pooler)."""
    # Render/Railway/Heroku hand out postgres:// URLs; SQLAlchemy async needs the driver name.
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://"):
        raw = "postgresql+asyncpg://" + raw[len("postgresql://"):]
    if not raw.startswith("postgresql+asyncpg://"):
        return raw, {}, False

    # Hosted Postgres (Neon, Antideploy, Supabase) adds libpq-only query options that asyncpg
    # rejects as unknown keywords. Move sslmode into asyncpg's own `ssl` argument; drop the rest.
    parts = urlsplit(raw)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    connect_args: dict = {}
    sslmode = query.pop("sslmode", None)
    if sslmode:
        connect_args["ssl"] = sslmode
    query.pop("channel_binding", None)

    # A "-pooler" host is PgBouncer in transaction mode: prepared statements can't be cached there.
    pooled = "-pooler." in (parts.hostname or "")
    if pooled:
        connect_args["statement_cache_size"] = 0
        query["prepared_statement_cache_size"] = "0"
    return urlunsplit(parts._replace(query=urlencode(query))), connect_args, pooled


def _redis_url(raw: str) -> str:
    # Empty, "none" or "off" all mean: run without Redis.
    raw = raw.strip()
    return "" if raw.lower() in ("", "none", "off", "false", "disabled") else raw


class Settings:
    def __init__(self) -> None:
        self.database_url, self.database_connect_args, self.database_pooled = _db_url(os.getenv(
            "DATABASE_URL", "postgresql+asyncpg://linkpulse:linkpulse@localhost:5432/linkpulse"))
        # Set REDIS_URL to empty (or "none") to run without Redis (no cache; clicks logged in-process).
        self.redis_url = _redis_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        self.secret_key = os.getenv("SECRET_KEY", "dev-only-secret-change-me")
        self.base_url = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
        self.frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
        self.jwt_expire_minutes = int(os.getenv("JWT_EXPIRE_MINUTES", "720"))
        self.link_cache_ttl = int(os.getenv("LINK_CACHE_TTL", "300"))
        self.create_rate_limit = os.getenv("CREATE_RATE_LIMIT", "30/minute")
        self.password_rate_limit = os.getenv("PASSWORD_RATE_LIMIT", "10/10minutes")
        self.check_reachability = _bool("CHECK_REACHABILITY", True)
        self.trust_proxy_headers = _bool("TRUST_PROXY_HEADERS", False)
        self.auto_create_tables = _bool("AUTO_CREATE_TABLES", True)
        self.geoip_db_path = os.getenv("GEOIP_DB_PATH", "")
        self.safe_browsing_key = os.getenv("SAFE_BROWSING_API_KEY", "")
        self.extra_own_hosts = {h.strip().lower() for h in os.getenv("OWN_HOSTS", "").split(",") if h.strip()}

    @property
    def own_hosts(self) -> set[str]:
        """Hosts that belong to LinkPulse itself; links pointing here would loop."""
        hosts = set(self.extra_own_hosts)
        for url in (self.base_url, self.frontend_url):
            host = (urlsplit(url).hostname or "").lower()
            if host and host not in ("localhost", "127.0.0.1"):
                hosts.add(host)
        return hosts


settings = Settings()

if settings.secret_key == "dev-only-secret-change-me" and not settings.base_url.startswith("http://localhost"):
    raise RuntimeError("Set SECRET_KEY before deploying LinkPulse.")
