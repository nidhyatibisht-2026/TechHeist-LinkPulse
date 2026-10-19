from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User


def audit(session: AsyncSession, actor: User | None, action: str, target_type: str, target_id, detail: str = "") -> None:
    """Adds an audit row to the current transaction; the caller commits."""
    session.add(AuditLog(actor_id=actor.id if actor else None, action=action, target_type=target_type,
                         target_id=str(target_id), detail=detail[:2000]))
