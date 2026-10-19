# No `from __future__ import annotations` here: slowapi's @limiter.limit wraps endpoints, and
# FastAPI would then resolve string annotations against slowapi's globals, not this module's.

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.rules import RULE_ORDER, Visit, evaluate
from app.core.urls import normalize_url
from app.db import get_session
from app.models import Link, TargetRule, User, link_tags
from app.ratelimit import limiter
from app.schemas import LinkCreate, LinkUpdate, SimulateIn, ValidateIn
from app.security import can_access, get_current_user, hash_password
from app.services import analytics, cache, safety
from app.services import links as svc
from app.services.audit import audit
from app.services.qr import qr_bytes

router = APIRouter(prefix="/api/links", tags=["links"])


async def owned_link(link_id: int, session: AsyncSession, user: User) -> Link:
    link = await svc.get_link_full(session, link_id)
    # 404 (not 403) for other users' links, so IDs can't be probed.
    if link is None or not can_access(user, link.owner_id):
        raise HTTPException(404, "Link not found.")
    return link


def _fail(result: svc.ValidationResult | None = None, issues: list | None = None, status: int = 422):
    errors = [i.as_dict() for i in (result.errors if result else [])] + \
             [i.as_dict() for i in (issues or []) if i.severity == "error"]
    warnings = [i.as_dict() for i in (result.warnings if result else [])]
    raise HTTPException(status, {"message": errors[0]["message"] if errors else "Invalid input.",
                                 "errors": errors, "warnings": warnings})


@router.get("")
async def list_links(
    q: str | None = None,
    status: str | None = Query(default=None, description="active|paused|disabled|expired|scheduled|limit_reached|archived"),
    campaign_id: int | None = None,
    tag_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    query = select(Link).options(selectinload(Link.tags), selectinload(Link.targets), selectinload(Link.campaign),
                                 selectinload(Link.owner))
    if user.role != "admin":
        query = query.where(Link.owner_id == user.id)
    if status != "archived":
        query = query.where(Link.status != "archived")
    if q:
        like = f"%{q.strip().lower()}%"
        query = query.where(or_(Link.code.like(like), func.lower(Link.destination).like(like),
                                func.lower(Link.title).like(like)))
    if campaign_id:
        query = query.where(Link.campaign_id == campaign_id)
    if tag_id:
        query = query.where(Link.id.in_(select(link_tags.c.link_id).where(link_tags.c.tag_id == tag_id)))
    if status in ("active", "paused", "disabled", "archived"):
        # "active" here means stored status; the effective filter below refines it.
        query = query.where(Link.status == status)

    rows = (await session.scalars(query.order_by(Link.created_at.desc()))).all()
    now = datetime.now(timezone.utc)
    if status in ("active", "expired", "scheduled", "limit_reached"):
        rows = [l for l in rows if svc.effective_status(l, now) == status]
    total = len(rows)
    page_rows = rows[(page - 1) * page_size: page * page_size]
    sparks = await analytics.sparklines(session, [l.id for l in page_rows])
    items = [{**svc.link_out(l, now), "spark": sparks.get(l.id, [])} for l in page_rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/validate")
async def validate(data: ValidateIn, session: AsyncSession = Depends(get_session),
                   user: User = Depends(get_current_user)):
    """Step 1 of the wizard: report problems BEFORE anything is saved."""
    if data.link_id:
        await owned_link(data.link_id, session, user)
    result = await svc.validate_link_input(session, data.destination, data.alias, exclude_link_id=data.link_id)
    out = result.as_dict()
    out["preview_short_url"] = svc.short_url(result.alias) if result.alias else f"{settings.base_url}/<random 7 characters>"
    return out


@router.post("", status_code=201)
@limiter.limit(settings.create_rate_limit)
async def create(request: Request, data: LinkCreate, session: AsyncSession = Depends(get_session),
                 user: User = Depends(get_current_user)):
    result = await svc.validate_link_input(session, data.destination, data.alias, network=False)
    extra = await svc.validate_extras(session, data.expired_url, data.targets, data.starts_at, data.expires_at)
    if not result.ok or any(i.severity == "error" for i in extra):
        _fail(result, extra)
    try:
        campaign = await svc.owned_campaign(session, user, data.campaign_id)
        tags = await svc.owned_tags(session, user, data.tag_ids)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    utm = data.utm.model_dump() if data.utm else {}
    if campaign and not data.utm:
        utm = {"utm_source": campaign.utm_source, "utm_medium": campaign.utm_medium,
               "utm_campaign": campaign.utm_campaign}
    try:
        link = await svc.create_link(
            session, user, destination=result.destination, alias=result.alias, title=data.title,
            campaign=campaign, tags=tags, password=data.password, starts_at=data.starts_at,
            expires_at=data.expires_at, expired_url=data.expired_url, click_cap=data.click_cap,
            targets=data.targets, utm=utm)
    except ValueError as exc:
        raise HTTPException(409, {"message": str(exc), "errors": [{"field": "alias", "code": "alias_taken",
                                                                     "message": str(exc)}], "warnings": []})
    link = await svc.get_link_full(session, link.id)
    return {**svc.link_out(link), "warnings": [w.as_dict() for w in result.warnings]}


@router.get("/{link_id}")
async def get_link(link_id: int, session: AsyncSession = Depends(get_session),
                   user: User = Depends(get_current_user)):
    return svc.link_out(await owned_link(link_id, session, user))


@router.patch("/{link_id}")
async def update_link(link_id: int, data: LinkUpdate, session: AsyncSession = Depends(get_session),
                      user: User = Depends(get_current_user)):
    link = await owned_link(link_id, session, user)
    if link.status == "disabled" and user.role != "admin":
        raise HTTPException(403, "An administrator disabled this link. Contact support to restore it.")
    fields = data.model_dump(exclude_unset=True)

    if "destination" in fields and fields["destination"] is not None:
        url, issues = await svc.validate_destination(session, fields["destination"], network=False)
        if any(i.severity == "error" for i in issues):
            _fail(issues=issues)
        link.destination = url
    extra = await svc.validate_extras(
        session, fields.get("expired_url"), data.targets or [],
        fields.get("starts_at", link.starts_at), fields.get("expires_at", link.expires_at))
    # Allow editing an already-expired link without forcing a new expiry, unless expiry itself was changed.
    extra = [i for i in extra if not (i.code == "past" and "expires_at" not in fields)]
    if any(i.severity == "error" for i in extra):
        _fail(issues=extra)

    # Explicit null clears optional settings (expiry, cap, schedule); title/status can't be null.
    for name in ("starts_at", "expires_at", "click_cap"):
        if name in fields:
            setattr(link, name, fields[name])
    if "title" in fields:
        link.title = fields["title"] or ""
    if fields.get("status"):
        link.status = fields["status"]
    if "expired_url" in fields:
        link.expired_url = normalize_url(fields["expired_url"]) if fields["expired_url"] else None
    if "campaign_id" in fields:
        try:
            campaign = await svc.owned_campaign(session, user, fields["campaign_id"])
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        link.campaign_id = campaign.id if campaign else None
    if data.tag_ids is not None:
        try:
            link.tags = await svc.owned_tags(session, user, data.tag_ids)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
    if data.targets is not None:
        link.targets = [TargetRule(kind=t.kind, value=t.value, destination=normalize_url(t.destination),
                                   priority=t.priority) for t in data.targets]
    if data.remove_password:
        link.password_hash = None
    elif data.password:
        link.password_hash = hash_password(data.password)

    audit(session, user, "link.update", "link", link.id, ", ".join(sorted(fields)))
    await session.commit()
    await cache.invalidate_link(link.code)
    return svc.link_out(await svc.get_link_full(session, link.id))


@router.delete("/{link_id}")
async def archive_link(link_id: int, session: AsyncSession = Depends(get_session),
                       user: User = Depends(get_current_user)):
    """Soft delete: the link stops working but its analytics stay in every report."""
    link = await owned_link(link_id, session, user)
    link.status = "archived"
    audit(session, user, "link.archive", "link", link.id, link.code)
    await session.commit()
    await cache.invalidate_link(link.code)
    return {"ok": True}


@router.get("/{link_id}/qr")
async def qr(link_id: int, fmt: str = Query(default="png", pattern="^(png|svg)$"),
             download: bool = False, session: AsyncSession = Depends(get_session),
             user: User = Depends(get_current_user)):
    link = await owned_link(link_id, session, user)
    data, media_type = qr_bytes(link.code, fmt)
    headers = {"Content-Disposition": f'attachment; filename="linkpulse-{link.code}.{fmt}"'} if download else {}
    return Response(content=data, media_type=media_type, headers=headers)


@router.post("/{link_id}/simulate")
async def simulate(link_id: int, data: SimulateIn, session: AsyncSession = Depends(get_session),
                   user: User = Depends(get_current_user)):
    """Runs the SAME evaluate() function visitors hit, with inputs you choose. Nothing is logged or counted."""
    link = await owned_link(link_id, session, user)
    view = svc.view_from_snapshot(svc.snapshot(link))
    blocked = await safety.blocked_domain_for(session, link.destination)
    decision = evaluate(view, Visit(now=data.at or datetime.now(timezone.utc), device=data.device, os=data.os,
                                    country=data.country.upper() if data.country else None,
                                    password_ok=data.password_ok, blocked_domain=blocked))
    return {**decision.as_dict(), "rule_order": [{"rule": r, "label": l} for r, l in RULE_ORDER]}


@router.get("/{link_id}/analytics")
async def link_analytics(link_id: int, days: int = Query(default=30, ge=1, le=365),
                         session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    link = await owned_link(link_id, session, user)
    return await analytics.report(session, user, days=days, link_id=link.id)


@router.get("/{link_id}/events")
async def link_events(link_id: int, limit: int = Query(default=50, ge=1, le=200),
                      session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    """Raw recent visits, including filtered bots with the reason. Transparency for the filter."""
    link = await owned_link(link_id, session, user)
    return await analytics.recent_events(session, link.id, limit)
