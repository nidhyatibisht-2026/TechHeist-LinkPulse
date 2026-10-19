"""LinkPulse API. Run locally: uvicorn app.main:app --reload"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal, create_tables, engine
from app.ratelimit import limiter
from app.routers import admin, auth, campaigns, links, redirect
from app.services import cache, pages
from app.services.safety import all_blocked_domains

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("linkpulse")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_tables:
        await create_tables()
    async with SessionLocal() as session:
        await cache.blocklist_load(sorted(await all_blocked_domains(session)))
    app.state.arq = None
    if settings.redis_url:
        try:
            from arq import create_pool
            from arq.connections import RedisSettings

            app.state.arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        except Exception as exc:  # noqa: BLE001
            log.warning("Redis queue unavailable; clicks will be logged in-process: %s", exc)
    yield
    if app.state.arq is not None:
        await app.state.arq.aclose()
    await engine.dispose()


app = FastAPI(title="LinkPulse API", version="1.0.0", lifespan=lifespan,
              description="Link management, rule-based redirection and click analytics.")
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RateLimitExceeded)
async def rate_limited(request: Request, exc: RateLimitExceeded):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": f"Too many requests ({exc.detail}). Wait a moment and try again."},
                            status_code=429)
    return pages.message("rate_limited")


@app.get("/health", tags=["system"])
async def health():
    """Liveness + dependency check for the hosting platform and the demo."""
    db_ok = True
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    redis_ok = None
    r = cache.get_redis()
    if r is not None:
        try:
            redis_ok = bool(await r.ping())
        except Exception:  # noqa: BLE001
            redis_ok = False
    return {"ok": db_ok, "database": db_ok, "redis": redis_ok, "queue": app.state.arq is not None}


@app.get("/", include_in_schema=False)
async def root():
    return JSONResponse({"service": "LinkPulse", "docs": "/docs", "app": settings.frontend_url})


# Order matters: API routes first, the catch-all /{code} redirect route LAST.
app.include_router(auth.router)
app.include_router(links.router)
app.include_router(campaigns.router)
app.include_router(admin.router)
app.include_router(admin.import_router)
app.include_router(redirect.router)
