"""Link business logic shared by the API, the CSV importer and the redirect engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.codes import alias_problems, generate_code, normalize_alias
from app.core.rules import LinkView, Target, as_utc
from app.core.urls import Issue, add_utm, host_of, normalize_url, url_issues
from app.models import Campaign, Link, Tag, TargetRule, User
from app.security import hash_password
from app.services import cache, safety


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def short_url(code: str) -> str:
    return f"{settings.base_url}/{code}"


def effective_status(link: Link, now: datetime | None = None) -> str:
    """What a visitor would experience right now (stored status + time/cap rules)."""
    now = now or utcnow()
    if link.status in ("disabled", "archived", "paused"):
        return link.status
    if link.starts_at and as_utc(link.starts_at) > now:
        return "scheduled"
    if link.expires_at and as_utc(link.expires_at) <= now:
        return "expired"
    if link.click_cap is not None and link.click_count >= link.click_cap:
        return "limit_reached"
    return "active"


# ---------------- snapshots (what the redirect engine and cache use) ----------------
def snapshot(link: Link) -> dict:
    iso = lambda d: as_utc(d).isoformat() if d else None  # noqa: E731
    return {
        "id": link.id, "code": link.code, "title": link.title, "destination": link.destination, "status": link.status,
        "starts_at": iso(link.starts_at), "expires_at": iso(link.expires_at), "expired_url": link.expired_url,
        "click_cap": link.click_cap, "click_count": link.click_count, "password_hash": link.password_hash,
        "targets": [{"kind": t.kind, "value": t.value, "destination": t.destination, "priority": t.priority}
                    for t in link.targets],
    }


def view_from_snapshot(s: dict) -> LinkView:
    parse = lambda v: datetime.fromisoformat(v) if v else None  # noqa: E731
    return LinkView(
        id=s["id"], code=s["code"], destination=s["destination"], status=s["status"],
        starts_at=parse(s["starts_at"]), expires_at=parse(s["expires_at"]), expired_url=s["expired_url"],
        click_cap=s["click_cap"], click_count=s["click_count"], has_password=bool(s["password_hash"]),
        targets=[Target(**t) for t in s["targets"]],
    )


async def load_snapshot(session: AsyncSession, code: str) -> dict | None:
    """Cache-aside lookup: Redis first, database on miss, then populate the cache."""
    cached = await cache.get_link(code)
    if cached == cache.MISSING:
        return None
    if isinstance(cached, dict):
        return cached
    link = await session.scalar(select(Link).options(selectinload(Link.targets)).where(Link.code == code))
    snap = snapshot(link) if link else None
    await cache.set_link(code, snap)
    return snap


# ---------------- validation ----------------
@dataclass
class ValidationResult:
    destination: str
    alias: str | None
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, issues: list[Issue]) -> None:
        for i in issues:
            (self.errors if i.severity == "error" else self.warnings).append(i)

    def as_dict(self) -> dict:
        return {"ok": self.ok, "destination": self.destination, "alias": self.alias,
                "errors": [i.as_dict() for i in self.errors], "warnings": [i.as_dict() for i in self.warnings]}


async def alias_taken(session: AsyncSession, alias: str, exclude_link_id: int | None = None) -> bool:
    q = select(Link.id).where(Link.code == alias)
    if exclude_link_id:
        q = q.where(Link.id != exclude_link_id)
    return (await session.scalar(q)) is not None


async def validate_destination(session: AsyncSession, raw_url: str, field_name: str = "destination",
                               network: bool = True) -> tuple[str, list[Issue]]:
    url = normalize_url(raw_url)
    issues = url_issues(url, field_name, settings.own_hosts)
    if any(i.severity == "error" for i in issues):
        return url, issues
    blocked = await safety.blocked_domain_for(session, url)
    if blocked:
        issues.append(Issue(field_name, "blocklisted", f"The domain {blocked} is blocked on LinkPulse."))
        return url, issues
    if network:
        threat = await safety.safe_browsing_threat(url)
        if threat:
            issues.append(Issue(field_name, "unsafe",
                                f"Google Safe Browsing flags this URL ({threat.replace('_', ' ').lower()})."))
            return url, issues
        if settings.check_reachability:
            ok, detail = await safety.resolve_public(host_of(url))
            if not ok and "private" in detail:
                issues.append(Issue(field_name, "private", "This domain points to a private network address."))
            else:
                status, detail = await safety.check_reachable(url)
                if status != "ok":
                    issues.append(Issue(field_name, "unreachable",
                                        f"We could not reach this page: {detail}. Check the URL, "
                                        "or publish anyway if the page is not live yet.", "warning"))
    return url, issues


async def validate_link_input(session: AsyncSession, raw_url: str, raw_alias: str | None,
                              exclude_link_id: int | None = None, network: bool = True) -> ValidationResult:
    url, issues = await validate_destination(session, raw_url, "destination", network)
    alias = normalize_alias(raw_alias)
    result = ValidationResult(destination=url, alias=alias)
    result.add(issues)
    if alias:
        problems = alias_problems(alias)
        for p in problems:
            result.errors.append(Issue("alias", "alias_format", p))
        if not problems and await alias_taken(session, alias, exclude_link_id):
            result.errors.append(Issue("alias", "alias_taken", f"/{alias} is already taken. Try another alias."))
    return result


async def validate_extras(session: AsyncSession, expired_url: str | None, targets: list,
                          starts_at: datetime | None, expires_at: datetime | None) -> list[Issue]:
    """Secondary URLs and dates. No network checks (keep creation fast)."""
    issues: list[Issue] = []
    if expired_url:
        _, i = await validate_destination(session, expired_url, "expired_url", network=False)
        issues += i
    for n, t in enumerate(targets):
        _, i = await validate_destination(session, t.destination, f"targets.{n}.destination", network=False)
        issues += i
    now = utcnow()
    if expires_at and expires_at <= now:
        issues.append(Issue("expires_at", "past", "Expiry date is in the past."))
    if starts_at and expires_at and starts_at >= expires_at:
        issues.append(Issue("starts_at", "order", "Start time must be before the expiry date."))
    return issues


# ---------------- ownership helpers ----------------
async def owned_campaign(session: AsyncSession, user: User, campaign_id: int | None) -> Campaign | None:
    if campaign_id is None:
        return None
    c = await session.get(Campaign, campaign_id)
    if c is None or (user.role != "admin" and c.owner_id != user.id):
        raise LookupError("Campaign not found.")
    return c


async def owned_tags(session: AsyncSession, user: User, tag_ids: list[int]) -> list[Tag]:
    if not tag_ids:
        return []
    tags = (await session.scalars(select(Tag).where(Tag.id.in_(tag_ids)))).all()
    if len(tags) != len(set(tag_ids)) or any(user.role != "admin" and t.owner_id != user.id for t in tags):
        raise LookupError("One or more tags were not found.")
    return list(tags)


# ---------------- create ----------------
async def create_link(session: AsyncSession, owner: User, *, destination: str, alias: str | None, title: str = "",
                      campaign: Campaign | None = None, tags: list[Tag] | None = None,
                      password: str | None = None, starts_at=None, expires_at=None, expired_url=None,
                      click_cap=None, targets: list | None = None, utm: dict | None = None,
                      commit: bool = True) -> Link:
    """Assumes inputs were validated. Generates a code with collision retry when no alias is given."""
    final_destination = add_utm(destination, utm or {})
    link = Link(
        destination=final_destination, title=title or "", owner_id=owner.id,
        campaign_id=campaign.id if campaign else None,
        password_hash=hash_password(password) if password else None,
        starts_at=starts_at, expires_at=expires_at, expired_url=normalize_url(expired_url) if expired_url else None,
        click_cap=click_cap, click_count=0,
    )
    link.tags = tags or []
    link.targets = [TargetRule(kind=t.kind, value=t.value, destination=normalize_url(t.destination),
                               priority=t.priority) for t in (targets or [])]

    if alias:
        link.code = alias
        try:
            async with session.begin_nested():
                session.add(link)
                await session.flush()
        except IntegrityError:
            raise ValueError(f"/{alias} was just taken by someone else. Try another alias.")
    else:
        for attempt in range(5):
            # The unique index is the source of truth; a savepoint lets us retry on collision.
            link.code = generate_code(7 + attempt // 3)
            try:
                async with session.begin_nested():
                    session.add(link)
                    await session.flush()
                break
            except IntegrityError:
                # Rolling back the savepoint expunges the pending link; loop and retry.
                continue
        else:
            raise RuntimeError("Could not generate a unique code. Try again.")

    if commit:
        await session.commit()
    await cache.invalidate_link(link.code)  # clears any negative-cache entry for this code
    return link


async def get_link_full(session: AsyncSession, link_id: int) -> Link | None:
    return await session.scalar(
        select(Link).options(selectinload(Link.tags), selectinload(Link.targets), selectinload(Link.campaign),
                             selectinload(Link.owner))
        .where(Link.id == link_id)
        # Reload even if the object is already in the session, so edits (e.g. a new campaign) show up.
        .execution_options(populate_existing=True))


def link_out(link: Link, now: datetime | None = None) -> dict:
    return {
        "id": link.id,
        "code": link.code,
        "short_url": short_url(link.code),
        "destination": link.destination,
        "title": link.title,
        "status": link.status,
        "effective_status": effective_status(link, now),
        "disabled_reason": link.disabled_reason,
        "campaign": {"id": link.campaign.id, "name": link.campaign.name} if link.campaign else None,
        "tags": [{"id": t.id, "name": t.name, "color": t.color} for t in link.tags],
        "has_password": bool(link.password_hash),
        "starts_at": as_utc(link.starts_at),
        "expires_at": as_utc(link.expires_at),
        "expired_url": link.expired_url,
        "click_cap": link.click_cap,
        "click_count": link.click_count,
        "targets": [{"kind": t.kind, "value": t.value, "destination": t.destination, "priority": t.priority}
                    for t in link.targets],
        "health_status": link.health_status,
        "health_detail": link.health_detail,
        "health_checked_at": as_utc(link.health_checked_at),
        "owner_email": link.owner.email if link.owner else None,
        "created_at": as_utc(link.created_at),
        "updated_at": as_utc(link.updated_at),
    }


async def count_links(session: AsyncSession, owner_id: int | None = None) -> int:
    q = select(func.count(Link.id))
    if owner_id:
        q = q.where(Link.owner_id == owner_id)
    return int(await session.scalar(q) or 0)
