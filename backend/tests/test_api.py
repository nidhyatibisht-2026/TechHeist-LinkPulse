"""End-to-end API tests.  pip install -r requirements-dev.txt  then  pytest -q"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import auth, register

# One event loop for the whole module: the database engine is shared between tests.
pytestmark = pytest.mark.asyncio(loop_scope="session")


async def make_link(client, headers, **body):
    body.setdefault("destination", "https://example.com/page")
    r = await client.post("/api/links", json=body, headers=auth(headers))
    assert r.status_code == 201, r.text
    return r.json()


async def test_first_user_is_admin_second_is_user(client):
    a = await register(client, "a@test.dev")
    b = await register(client, "b@test.dev")
    assert a["_user"]["role"] == "admin"
    assert b["_user"]["role"] == "user"


async def test_create_redirect_and_count(client):
    h = await register(client, "a@test.dev")
    link = await make_link(client, h, alias="Promo")
    assert link["code"] == "promo"  # aliases are case-insensitive
    r = await client.get("/PROMO")
    assert r.status_code == 302
    assert r.headers["location"] == "https://example.com/page"
    assert "no-store" in r.headers["cache-control"]
    stats = (await client.get(f"/api/links/{link['id']}/analytics", headers=auth(h))).json()
    assert stats["totals"]["clicks"] == 1


async def test_bots_are_redirected_but_not_counted(client):
    h = await register(client, "a@test.dev")
    link = await make_link(client, h)
    r = await client.get(f"/{link['code']}", headers={"User-Agent": "WhatsApp/2.23.20.0 A"})
    assert r.status_code == 302
    stats = (await client.get(f"/api/links/{link['id']}/analytics", headers=auth(h))).json()
    assert stats["totals"]["clicks"] == 0
    assert stats["totals"]["filtered_bots"] == 1


async def test_users_cannot_see_each_others_links(client):
    """IDOR check: guessing another user's link ID must look exactly like a missing link."""
    a = await register(client, "a@test.dev")
    b = await register(client, "b@test.dev")
    link = await make_link(client, b)
    for method, path in [("GET", f"/api/links/{link['id']}"), ("PATCH", f"/api/links/{link['id']}"),
                         ("DELETE", f"/api/links/{link['id']}"), ("GET", f"/api/links/{link['id']}/analytics"),
                         ("GET", f"/api/links/{link['id']}/qr")]:
        other = await register(client, f"c{method}{len(path)}@test.dev")
        r = await client.request(method, path, headers=auth(other), json={} if method == "PATCH" else None)
        assert r.status_code == 404, (method, path, r.status_code)
    # ...but the admin (first user) can see it.
    assert (await client.get(f"/api/links/{link['id']}", headers=auth(a))).status_code == 200
    listing = (await client.get("/api/links", headers=auth(b))).json()
    assert listing["total"] == 1


async def test_validation_errors_and_warnings(client):
    h = await register(client, "a@test.dev")
    await make_link(client, h, alias="taken")
    r = (await client.post("/api/links/validate", json={"destination": "http://example.com", "alias": "taken"},
                           headers=auth(h))).json()
    assert {e["code"] for e in r["errors"]} == {"alias_taken"}
    assert {w["code"] for w in r["warnings"]} == {"insecure"}
    for bad in ("javascript:alert(1)", "http://127.0.0.1", "http://testserver/x"):
        r = await client.post("/api/links", json={"destination": bad}, headers=auth(h))
        assert r.status_code == 422, bad
    r = await client.post("/api/links", json={"destination": "https://example.com", "alias": "api"}, headers=auth(h))
    assert r.status_code == 422


async def test_click_cap_is_exact_under_concurrency(client):
    h = await register(client, "a@test.dev")
    link = await make_link(client, h, click_cap=5)
    responses = await asyncio.gather(*(client.get(f"/{link['code']}") for _ in range(12)))
    codes = sorted(r.status_code for r in responses)
    assert codes.count(302) == 5
    assert codes.count(410) == 7
    detail = (await client.get(f"/api/links/{link['id']}", headers=auth(h))).json()
    assert detail["click_count"] == 5
    assert detail["effective_status"] == "limit_reached"


async def test_bots_cannot_use_or_bypass_a_cap(client):
    h = await register(client, "a@test.dev")
    link = await make_link(client, h, click_cap=1, title="Coupon")
    r = await client.get(f"/{link['code']}", headers={"User-Agent": "Slackbot-LinkExpanding 1.0"})
    assert r.status_code == 200 and "Coupon" in r.text and "example.com" not in r.text
    assert (await client.get(f"/{link['code']}")).status_code == 302  # the human still gets the one click


async def test_password_flow(client):
    h = await register(client, "a@test.dev")
    link = await make_link(client, h, password="secret12")
    assert (await client.get(f"/{link['code']}")).status_code == 200  # form
    assert (await client.post(f"/{link['code']}", data={"password": "wrong"})).status_code == 401
    r = await client.post(f"/{link['code']}", data={"password": "secret12"})
    assert r.status_code == 303 and r.headers["location"] == "https://example.com/page"
    assert f"lp_{link['code']}" in r.headers.get("set-cookie", "")


async def test_admin_disable_takes_effect_immediately_and_keeps_analytics(client):
    admin = await register(client, "admin@test.dev")
    user = await register(client, "u@test.dev")
    link = await make_link(client, user)
    assert (await client.get(f"/{link['code']}")).status_code == 302
    r = await client.post(f"/api/admin/links/{link['id']}/disable", json={"reason": "phishing report"},
                          headers=auth(admin))
    assert r.status_code == 200
    assert (await client.get(f"/{link['code']}")).status_code == 403
    stats = (await client.get(f"/api/links/{link['id']}/analytics", headers=auth(user))).json()
    assert stats["totals"]["clicks"] == 1
    assert stats["totals"]["blocked_attempts"] == 1
    # Users cannot re-enable an admin-disabled link.
    r = await client.patch(f"/api/links/{link['id']}", json={"status": "active"}, headers=auth(user))
    assert r.status_code == 403
    # Non-admins cannot use admin routes.
    assert (await client.get("/api/admin/users", headers=auth(user))).status_code == 403


async def test_blocklist_stops_existing_links(client):
    admin = await register(client, "admin@test.dev")
    link = await make_link(client, admin, destination="https://login.badsite.com/x")
    r = await client.post("/api/admin/blocklist", json={"domain": "badsite.com", "reason": "test"}, headers=auth(admin))
    assert r.json()["affected_links"] == 1
    assert (await client.get(f"/{link['code']}")).status_code == 403
    r = await client.post("/api/links", json={"destination": "https://badsite.com"}, headers=auth(admin))
    assert r.status_code == 422


async def test_expiry_with_fallback_and_targeting(client):
    h = await register(client, "a@test.dev")
    soon = (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()
    link = await make_link(client, h, expires_at=soon, expired_url="https://example.com/ended",
                           targets=[{"kind": "os", "value": "ios", "destination": "https://apps.apple.com/x"}])
    iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) Version/17.4 Mobile/15E148 Safari/604.1"
    r = await client.get(f"/{link['code']}", headers={"User-Agent": iphone})
    assert r.headers["location"] == "https://apps.apple.com/x"
    await asyncio.sleep(2.2)
    r = await client.get(f"/{link['code']}")
    assert r.status_code == 302 and r.headers["location"] == "https://example.com/ended"


async def test_simulator_matches_engine(client):
    h = await register(client, "a@test.dev")
    link = await make_link(client, h, targets=[{"kind": "device", "value": "mobile",
                                                "destination": "https://m.example.com"}])
    r = (await client.post(f"/api/links/{link['id']}/simulate", json={"device": "mobile"}, headers=auth(h))).json()
    assert r["action"] == "redirect" and r["url"] == "https://m.example.com"
    assert len(r["trace"]) == 8 and len(r["rule_order"]) == 8


async def test_csv_import_preview_and_commit(client):
    h = await register(client, "a@test.dev")
    await make_link(client, h, alias="exists")
    csv_text = ("destination,alias,campaign,tags,click_cap\n"
                "https://example.com/1,first,Spring,email;promo,\n"
                "https://example.com/2,first,,,\n"          # duplicate alias in file
                "https://example.com/3,exists,,,\n"         # alias already taken
                "javascript:alert(1),,,,\n"                 # bad scheme
                "example.com/5,,,,abc\n")                   # bad cap; URL gets https://
    r = await client.post("/api/import/preview", files={"file": ("links.csv", csv_text, "text/csv")},
                          headers=auth(h))
    body = r.json()
    assert r.status_code == 200, r.text
    assert body["summary"] == {"total": 5, "valid": 1, "warning": 0, "error": 4, "importable": 1}
    rows = [x["data"] for x in body["rows"] if x["status"] != "error"]
    r = await client.post("/api/import/commit", json={"rows": rows}, headers=auth(h))
    assert len(r.json()["created"]) == 1
    camps = (await client.get("/api/campaigns", headers=auth(h))).json()
    assert [c["name"] for c in camps] == ["Spring"]


async def test_dashboard_overview_shape(client):
    h = await register(client, "a@test.dev")
    link = await make_link(client, h)
    await client.get(f"/{link['code']}")
    r = (await client.get("/api/analytics/overview?days=7", headers=auth(h))).json()
    assert r["totals"]["clicks"] == 1
    assert len(r["series"]) == 7 and r["series"][-1]["clicks"] == 1
    assert r["top_links"][0]["code"] == link["code"]
