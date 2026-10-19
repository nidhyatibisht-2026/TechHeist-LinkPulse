from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, distinct, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Campaign, ClickEvent, Link, Tag, User
from app.schemas import CampaignIn, TagIn
from app.security import can_access, get_current_user
from app.services import analytics

router = APIRouter(prefix="/api", tags=["campaigns & tags"])
HUMAN = and_(ClickEvent.outcome == "redirect", ClickEvent.is_bot.is_(False))


def campaign_out(c: Campaign, links: int = 0, clicks: int = 0, unique: int = 0) -> dict:
    return {"id": c.id, "name": c.name, "description": c.description, "utm_source": c.utm_source,
            "utm_medium": c.utm_medium, "utm_campaign": c.utm_campaign, "created_at": c.created_at,
            "links": links, "clicks": clicks, "unique": unique}


async def owned_campaign(session: AsyncSession, user: User, campaign_id: int) -> Campaign:
    c = await session.get(Campaign, campaign_id)
    if c is None or not can_access(user, c.owner_id):
        raise HTTPException(404, "Campaign not found.")
    return c


@router.get("/campaigns")
async def list_campaigns(session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    q = select(Campaign)
    if user.role != "admin":
        q = q.where(Campaign.owner_id == user.id)
    campaigns = (await session.scalars(q.order_by(Campaign.created_at.desc()))).all()
    ids = [c.id for c in campaigns]
    link_counts = dict((await session.execute(
        select(Link.campaign_id, func.count(Link.id)).where(Link.campaign_id.in_(ids)).group_by(Link.campaign_id))).all()) if ids else {}
    click_rows = (await session.execute(
        select(Link.campaign_id, func.count(ClickEvent.id), func.count(distinct(ClickEvent.visitor_hash)))
        .select_from(ClickEvent).join(Link, Link.id == ClickEvent.link_id)
        .where(Link.campaign_id.in_(ids), HUMAN).group_by(Link.campaign_id))).all() if ids else []
    clicks = {r[0]: (int(r[1]), int(r[2])) for r in click_rows}
    return [campaign_out(c, int(link_counts.get(c.id, 0)), *clicks.get(c.id, (0, 0))) for c in campaigns]


@router.post("/campaigns", status_code=201)
async def create_campaign(data: CampaignIn, session: AsyncSession = Depends(get_session),
                          user: User = Depends(get_current_user)):
    c = Campaign(owner_id=user.id, **data.model_dump())
    session.add(c)
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(409, f"You already have a campaign named '{data.name}'.")
    return campaign_out(c)


@router.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: int, days: int = Query(default=30, ge=1, le=365),
                       session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    c = await owned_campaign(session, user, campaign_id)
    report = await analytics.report(session, user, days=days, campaign_id=c.id)
    return {**campaign_out(c, report["total_links"], report["totals"]["clicks"], report["totals"]["unique_visitors"]),
            "report": report}


@router.patch("/campaigns/{campaign_id}")
async def update_campaign(campaign_id: int, data: CampaignIn, session: AsyncSession = Depends(get_session),
                          user: User = Depends(get_current_user)):
    c = await owned_campaign(session, user, campaign_id)
    for k, v in data.model_dump().items():
        setattr(c, k, v)
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(409, f"You already have a campaign named '{data.name}'.")
    return campaign_out(c)


@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: int, session: AsyncSession = Depends(get_session),
                          user: User = Depends(get_current_user)):
    """Links are kept (campaign_id becomes empty); only the grouping is removed."""
    c = await owned_campaign(session, user, campaign_id)
    for link in (await session.scalars(select(Link).where(Link.campaign_id == c.id))).all():
        link.campaign_id = None
    await session.delete(c)
    await session.commit()
    return {"ok": True}


@router.get("/tags")
async def list_tags(session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    q = select(Tag)
    if user.role != "admin":
        q = q.where(Tag.owner_id == user.id)
    return [{"id": t.id, "name": t.name, "color": t.color} for t in (await session.scalars(q.order_by(Tag.name))).all()]


@router.post("/tags", status_code=201)
async def create_tag(data: TagIn, session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    t = Tag(owner_id=user.id, name=data.name.strip(), color=data.color)
    session.add(t)
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(409, f"You already have a tag named '{data.name}'.")
    return {"id": t.id, "name": t.name, "color": t.color}


@router.delete("/tags/{tag_id}")
async def delete_tag(tag_id: int, session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    t = await session.get(Tag, tag_id)
    if t is None or not can_access(user, t.owner_id):
        raise HTTPException(404, "Tag not found.")
    await session.delete(t)
    await session.commit()
    return {"ok": True}


@router.get("/analytics/overview")
async def overview(days: int = Query(default=30, ge=1, le=365), campaign_id: int | None = None,
                   session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    """User: their own links. Admin: the whole platform."""
    if campaign_id is not None:
        await owned_campaign(session, user, campaign_id)
    return await analytics.report(session, user, days=days, campaign_id=campaign_id)
