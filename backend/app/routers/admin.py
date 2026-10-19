# No `from __future__ import annotations` here: slowapi's @limiter.limit wraps endpoints, and
# FastAPI would then resolve string annotations against slowapi's globals, not this module's.

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.urls import domain_suffixes, host_of
from app.db import get_session
from app.models import AuditLog, BlockedDomain, Link, User
from app.ratelimit import limiter
from app.routers.auth import user_out
from app.schemas import BlockIn, DisableIn, ImportCommitIn, RoleIn
from app.security import get_current_user, require_admin
from app.services import cache, importer
from app.services import links as svc
from app.services.audit import audit

router = APIRouter(prefix="/api/admin", tags=["admin"])
import_router = APIRouter(prefix="/api/import", tags=["bulk import"])


# ---------------- users ----------------
@router.get("/users")
async def list_users(session: AsyncSession = Depends(get_session), admin: User = Depends(require_admin)):
    return [user_out(u) for u in (await session.scalars(select(User).order_by(User.created_at))).all()]


@router.patch("/users/{user_id}/role")
async def set_role(user_id: int, data: RoleIn, session: AsyncSession = Depends(get_session),
                   admin: User = Depends(require_admin)):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found.")
    if user.id == admin.id and data.role != "admin":
        raise HTTPException(400, "You can't remove your own admin access.")
    user.role = data.role
    audit(session, admin, "user.role", "user", user.id, data.role)
    await session.commit()
    return user_out(user)


# ---------------- link takedown ----------------
async def _set_disabled(session: AsyncSession, admin: User, link_id: int, disabled: bool, reason: str = "") -> dict:
    link = await svc.get_link_full(session, link_id)
    if link is None:
        raise HTTPException(404, "Link not found.")
    link.status = "disabled" if disabled else "active"
    link.disabled_reason = reason if disabled else None
    audit(session, admin, "link.disable" if disabled else "link.enable", "link", link.id, f"/{link.code}: {reason}")
    await session.commit()
    # Without this the cached snapshot would keep redirecting for up to LINK_CACHE_TTL seconds.
    await cache.invalidate_link(link.code)
    return svc.link_out(await svc.get_link_full(session, link.id))


@router.post("/links/{link_id}/disable")
async def disable_link(link_id: int, data: DisableIn, session: AsyncSession = Depends(get_session),
                       admin: User = Depends(require_admin)):
    return await _set_disabled(session, admin, link_id, True, data.reason)


@router.post("/links/{link_id}/enable")
async def enable_link(link_id: int, session: AsyncSession = Depends(get_session), admin: User = Depends(require_admin)):
    return await _set_disabled(session, admin, link_id, False)


# ---------------- domain blocklist ----------------
@router.get("/blocklist")
async def list_blocklist(session: AsyncSession = Depends(get_session), admin: User = Depends(require_admin)):
    rows = (await session.scalars(select(BlockedDomain).order_by(BlockedDomain.created_at.desc()))).all()
    return [{"id": b.id, "domain": b.domain, "reason": b.reason, "created_at": b.created_at} for b in rows]


@router.post("/blocklist", status_code=201)
async def add_block(data: BlockIn, session: AsyncSession = Depends(get_session), admin: User = Depends(require_admin)):
    domain = (host_of(data.domain) if "://" in data.domain else data.domain).strip().lower().strip(".")
    if domain.startswith("www."):
        domain = domain[4:]
    if "." not in domain:
        raise HTTPException(422, "Enter a domain such as example.com.")
    session.add(BlockedDomain(domain=domain, reason=data.reason, created_by=admin.id))
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(409, f"{domain} is already blocked.")

    # Links pointing at the domain stop redirecting immediately via the redirect-time check.
    # Optionally also mark them disabled so owners see why.
    affected = [l for l in (await session.scalars(select(Link).where(Link.status.in_(("active", "paused"))))).all()
                if domain in domain_suffixes(host_of(l.destination))]
    if data.disable_existing:
        for l in affected:
            l.status, l.disabled_reason = "disabled", f"Destination domain {domain} was blocklisted"
    audit(session, admin, "blocklist.add", "domain", domain, f"{data.reason} (affected links: {len(affected)})")
    await session.commit()
    await cache.blocklist_change(add=domain)
    for l in affected:
        await cache.invalidate_link(l.code)
    return {"domain": domain, "affected_links": len(affected), "disabled": len(affected) if data.disable_existing else 0}


@router.delete("/blocklist/{block_id}")
async def remove_block(block_id: int, session: AsyncSession = Depends(get_session),
                       admin: User = Depends(require_admin)):
    b = await session.get(BlockedDomain, block_id)
    if b is None:
        raise HTTPException(404, "Blocked domain not found.")
    domain = b.domain
    await session.delete(b)
    audit(session, admin, "blocklist.remove", "domain", domain)
    await session.commit()
    await cache.blocklist_change(remove=domain)
    return {"ok": True}


# ---------------- audit log ----------------
@router.get("/audit")
async def audit_log(limit: int = Query(default=100, ge=1, le=500), session: AsyncSession = Depends(get_session),
                    admin: User = Depends(require_admin)):
    rows = (await session.scalars(select(AuditLog).options(selectinload(AuditLog.actor))
                                  .order_by(desc(AuditLog.created_at)).limit(limit))).all()
    return [{"id": a.id, "actor": a.actor.email if a.actor else "system", "action": a.action,
             "target_type": a.target_type, "target_id": a.target_id, "detail": a.detail,
             "created_at": a.created_at} for a in rows]


# ---------------- bulk import ----------------
@import_router.get("/template", response_class=PlainTextResponse)
async def template():
    return PlainTextResponse(importer.TEMPLATE, media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="linkpulse-import-template.csv"'})


@import_router.post("/preview")
async def preview(file: UploadFile = File(...), session: AsyncSession = Depends(get_session),
                  user: User = Depends(get_current_user)):
    content = await file.read(importer.MAX_BYTES + 1)
    try:
        rows = importer.parse_csv(content)
    except importer.ImportFileError as exc:
        raise HTTPException(422, str(exc))
    results = await importer.check_rows(session, rows)
    return {"summary": importer.summarize(results), "rows": results}


@import_router.post("/commit")
@limiter.limit("10/hour")
async def commit(request: Request, data: ImportCommitIn, session: AsyncSession = Depends(get_session),
                 user: User = Depends(get_current_user)):
    result = await importer.commit_rows(session, user, data.rows)
    audit(session, user, "import.commit", "user", user.id, f"created {len(result['created'])} links")
    await session.commit()
    return result
