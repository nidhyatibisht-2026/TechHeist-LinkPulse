"""Integration-test setup. Runs the real app against SQLite with Redis disabled,
so `pytest` works on any laptop with no services running.

Environment variables MUST be set before `app` is imported (settings read them at import).
"""
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_linkpulse.db"
os.environ["REDIS_URL"] = ""
os.environ["CHECK_REACHABILITY"] = "false"
os.environ["BASE_URL"] = "http://testserver"
# BASE_URL is not localhost, so config.py refuses the default dev secret; give tests their own.
os.environ["SECRET_KEY"] = "test-only-secret-not-for-production"
os.environ["CREATE_RATE_LIMIT"] = "1000/minute"

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


@pytest.fixture
async def fresh_db():
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    app.state.arq = None  # no queue: clicks are logged with BackgroundTasks
    try:
        app.state.limiter.reset()  # in-memory rate-limit counters from earlier tests
    except Exception:  # noqa: BLE001
        pass
    yield


@pytest.fixture
async def client(fresh_db):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver",
                                 headers={"User-Agent": BROWSER_UA}) as c:
        yield c


async def register(client, email: str, password: str = "Passw0rd!") -> dict:
    r = await client.post("/api/auth/register", json={"email": email, "password": password, "name": email})
    assert r.status_code == 200, r.text
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}", "_user": body["user"]}


def auth(h: dict) -> dict:
    return {k: v for k, v in h.items() if not k.startswith("_")}
