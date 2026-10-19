"""Bulk import in two stages:

  1. preview: parse the CSV and report every row as valid / warning / error,
     including duplicates inside the file and aliases already taken
  2. commit:  the client sends back the rows it wants; we RE-VALIDATE everything
     (never trust the client) and create the valid ones in one transaction

Expected columns (header names are case-insensitive):
  destination (or url) - required
  alias, title, campaign, tags (separated by ; or |), expires_at (ISO date), click_cap
Reachability is not checked per row (1000 HTTP requests would take minutes);
the scheduled health check covers imported links within 30 minutes.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.codes import alias_problems, normalize_alias
from app.core.urls import blocked_match, host_of, normalize_url, url_issues
from app.models import Campaign, Link, Tag, User
from app.schemas import ImportRow
from app.services import links as link_service
from app.services.safety import all_blocked_domains

MAX_ROWS = 1000
MAX_BYTES = 1_000_000
HEADER_ALIASES = {"url": "destination", "long_url": "destination", "link": "destination",
                  "slug": "alias", "short_code": "alias", "code": "alias", "expiry": "expires_at",
                  "expires": "expires_at", "cap": "click_cap", "click_limit": "click_cap", "name": "title"}
TEMPLATE = ("destination,alias,title,campaign,tags,expires_at,click_cap\n"
            "https://example.com/summer,summer-sale,Summer sale,Summer 2026,email;promo,2026-12-31,\n"
            "https://example.com/blog/launch,,Launch post,,blog,,500\n")


class ImportFileError(ValueError):
    pass


def parse_csv(content: bytes) -> list[ImportRow]:
    if len(content) > MAX_BYTES:
        raise ImportFileError("File is larger than 1 MB. Split it into smaller files.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportFileError("File must be UTF-8 encoded CSV. In Excel, use 'Save as CSV UTF-8'.")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ImportFileError("The file is empty.")
    headers = {}
    for h in reader.fieldnames:
        key = re.sub(r"\s+", "_", (h or "").strip().lower())
        headers[h] = HEADER_ALIASES.get(key, key)
    if "destination" not in headers.values():
        raise ImportFileError("Add a 'destination' column with the long URLs.")

    rows: list[ImportRow] = []
    for n, raw in enumerate(reader, start=2):  # row 1 is the header
        if len(rows) >= MAX_ROWS:
            raise ImportFileError(f"Import up to {MAX_ROWS} rows at a time.")
        data = {headers[k]: (v or "").strip() for k, v in raw.items() if k in headers}
        if not any(data.values()):
            continue
        expires, expires_invalid = None, False
        if data.get("expires_at"):
            try:
                expires = datetime.fromisoformat(data["expires_at"])
            except ValueError:
                expires_invalid = True
        cap = None
        if data.get("click_cap"):
            cap = int(data["click_cap"]) if data["click_cap"].isdigit() else -1
        rows.append(ImportRow(
            row=n, destination=data.get("destination", ""), alias=data.get("alias") or None,
            title=data.get("title", "")[:200], campaign=data.get("campaign") or None,
            tags=[t.strip() for t in re.split(r"[;|]", data.get("tags", "")) if t.strip()],
            expires_at=expires, expires_invalid=expires_invalid, click_cap=cap,
        ))
    return rows


async def check_rows(session: AsyncSession, rows: list[ImportRow]) -> list[dict]:
    blocked = await all_blocked_domains(session)
    aliases = [a for a in (normalize_alias(r.alias) for r in rows) if a]
    taken = set((await session.scalars(select(Link.code).where(Link.code.in_(aliases)))).all()) if aliases else set()
    now = datetime.now(timezone.utc)

    seen_alias: dict[str, int] = {}
    seen_dest: dict[str, int] = {}
    results = []
    for r in rows:
        errors: list[str] = []
        warnings: list[str] = []
        url = normalize_url(r.destination)
        for issue in url_issues(url, "destination", settings.own_hosts):
            (errors if issue.severity == "error" else warnings).append(issue.message)
        if not errors:
            hit = blocked_match(host_of(url), blocked)
            if hit:
                errors.append(f"The domain {hit} is blocked on LinkPulse.")

        alias = normalize_alias(r.alias)
        if alias:
            errors += alias_problems(alias)
            if alias in seen_alias:
                errors.append(f"Duplicate alias: also used on row {seen_alias[alias]}.")
            elif alias in taken:
                errors.append(f"/{alias} is already taken.")
            seen_alias.setdefault(alias, r.row)

        if url in seen_dest:
            warnings.append(f"Same destination as row {seen_dest[url]}.")
        seen_dest.setdefault(url, r.row)

        expires = r.expires_at
        if r.expires_invalid:
            errors.append("expires_at is not a valid date. Use YYYY-MM-DD.")
        elif expires is not None:
            expires = expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
            if expires <= now:
                errors.append("expires_at is in the past.")
        if r.click_cap is not None and r.click_cap < 1:
            errors.append("click_cap must be a whole number of 1 or more.")

        results.append({
            "row": r.row,
            "status": "error" if errors else ("warning" if warnings else "valid"),
            "errors": errors, "warnings": warnings,
            "data": {"row": r.row, "destination": url, "alias": alias, "title": r.title, "campaign": r.campaign,
                     "tags": r.tags, "expires_at": expires.isoformat() if expires else None,
                     "click_cap": r.click_cap if (r.click_cap or 0) >= 1 else None},
        })
    return results


def summarize(results: list[dict]) -> dict:
    s = {"total": len(results), "valid": 0, "warning": 0, "error": 0}
    for r in results:
        s[r["status"]] += 1
    s["importable"] = s["valid"] + s["warning"]
    return s


async def commit_rows(session: AsyncSession, user: User, rows: list[ImportRow]) -> dict:
    results = await check_rows(session, rows)
    campaign_cache: dict[str, Campaign] = {}
    tag_cache: dict[str, Tag] = {}

    async def campaign_named(name: str) -> Campaign:
        key = name.strip().lower()
        if key not in campaign_cache:
            c = await session.scalar(select(Campaign).where(Campaign.owner_id == user.id, Campaign.name == name.strip()))
            if c is None:
                c = Campaign(owner_id=user.id, name=name.strip()[:120])
                session.add(c)
                await session.flush()
            campaign_cache[key] = c
        return campaign_cache[key]

    async def tag_named(name: str) -> Tag:
        key = name.strip().lower()
        if key not in tag_cache:
            t = await session.scalar(select(Tag).where(Tag.owner_id == user.id, Tag.name == name.strip()))
            if t is None:
                t = Tag(owner_id=user.id, name=name.strip()[:50])
                session.add(t)
                await session.flush()
            tag_cache[key] = t
        return tag_cache[key]

    created, failed = [], []
    for res in results:
        if res["status"] == "error":
            failed.append({"row": res["row"], "errors": res["errors"]})
            continue
        d = res["data"]
        try:
            link = await link_service.create_link(
                session, user, destination=d["destination"], alias=d["alias"], title=d["title"],
                campaign=await campaign_named(d["campaign"]) if d["campaign"] else None,
                tags=[await tag_named(t) for t in d["tags"]],
                expires_at=datetime.fromisoformat(d["expires_at"]) if d["expires_at"] else None,
                click_cap=d["click_cap"], commit=False)
            created.append({"row": res["row"], "id": link.id, "code": link.code,
                            "short_url": link_service.short_url(link.code)})
        except (ValueError, RuntimeError) as exc:
            failed.append({"row": res["row"], "errors": [str(exc)]})
    await session.commit()
    return {"created": created, "failed": failed}
