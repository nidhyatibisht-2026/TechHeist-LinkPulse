"""Data model. The Link is the hub; everything else hangs off it.

    User 1--* Link *--1 Campaign
              Link *--* Tag
              Link 1--* TargetRule      (device / OS / country routing)
              Link 1--* ClickEvent      (every visit, including blocked ones)
    BlockedDomain, AuditLog             (governance)

Links are never hard-deleted: "delete" sets status=archived, so analytics for
expired, disabled or archived links stay intact (an explicit requirement).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# BIGINT on Postgres, INTEGER on SQLite (SQLite only auto-increments INTEGER primary keys).
BigId = BigInteger().with_variant(Integer(), "sqlite")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user", index=True)  # user | admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role!r}>"


class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_campaign_owner_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    # Default UTM values offered when a link is added to this campaign.
    utm_source: Mapped[str | None] = mapped_column(String(100))
    utm_medium: Mapped[str | None] = mapped_column(String(100))
    utm_campaign: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    links: Mapped[list[Link]] = relationship(back_populates="campaign")

    def __repr__(self) -> str:
        return f"<Campaign id={self.id} name={self.name!r} owner_id={self.owner_id}>"


link_tags = Table(
    "link_tags",
    Base.metadata,
    Column("link_id", ForeignKey("links.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_tag_owner_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(50))
    color: Mapped[str] = mapped_column(String(16), default="#0B7FB5")

    def __repr__(self) -> str:
        return f"<Tag id={self.id} name={self.name!r}>"


class Link(Base):
    __tablename__ = "links"
    __table_args__ = (
        Index("ix_links_owner_status", "owner_id", "status"),
        Index("ix_links_status_expires", "status", "expires_at"),
        CheckConstraint("click_cap IS NULL OR click_cap > 0", name="ck_link_click_cap_positive"),
        CheckConstraint("click_count >= 0", name="ck_link_click_count_non_negative"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # always lowercase
    destination: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(200), default="")
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), index=True)

    status: Mapped[str] = mapped_column(String(16), default="active", index=True)  # active|paused|disabled|archived
    disabled_reason: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_url: Mapped[str | None] = mapped_column(Text)
    click_cap: Mapped[int | None] = mapped_column(Integer)
    # Counted human redirects. For capped links this is incremented atomically in the
    # request path (it IS the cap guard); for uncapped links the worker increments it.
    click_count: Mapped[int] = mapped_column(Integer, default=0)

    health_status: Mapped[str] = mapped_column(String(16), default="unknown")  # unknown|ok|broken
    health_detail: Mapped[str | None] = mapped_column(Text)
    health_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    owner: Mapped[User] = relationship()
    campaign: Mapped[Campaign | None] = relationship(back_populates="links")
    tags: Mapped[list[Tag]] = relationship(secondary=link_tags)
    targets: Mapped[list[TargetRule]] = relationship(cascade="all, delete-orphan", order_by="TargetRule.priority")

    @property
    def is_expired(self) -> bool:
        """Return True if the link has passed its configured expiration timestamp."""
        if self.expires_at is None:
            return False
        now = utcnow()
        exp = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
        return now >= exp

    @property
    def is_cap_reached(self) -> bool:
        """Return True if the link has a click cap and has reached or exceeded it."""
        return self.click_cap is not None and self.click_count >= self.click_cap

    def __repr__(self) -> str:
        return f"<Link id={self.id} code={self.code!r} status={self.status!r} clicks={self.click_count}>"


class TargetRule(Base):
    __tablename__ = "target_rules"
    __table_args__ = (
        Index("ix_target_rules_link_priority", "link_id", "priority"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("links.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))   # device | os | country
    value: Mapped[str] = mapped_column(String(32))
    destination: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=0)


class ClickEvent(Base):
    """One row per visit attempt.

    outcome = redirect | blocked | expired | limit | password_failed | preview
    Analytics "clicks" = outcome == redirect AND is_bot == false.
    Logging non-redirect outcomes lets admins see that a disabled link is still
    being clicked, which is a useful abuse signal.
    """
    __tablename__ = "click_events"
    __table_args__ = (
        Index("ix_click_link_ts", "link_id", "ts"),
        Index("ix_click_ts", "ts"),
        Index("ix_click_analytics_filter", "link_id", "outcome", "is_bot", "ts"),
        Index("ix_click_geo_device", "link_id", "country", "device"),
    )
    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("links.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    outcome: Mapped[str] = mapped_column(String(20), default="redirect")
    source: Mapped[str] = mapped_column(String(8), default="link")  # link | qr
    referrer: Mapped[str | None] = mapped_column(Text)
    referrer_domain: Mapped[str] = mapped_column(String(255), default="Direct")
    device: Mapped[str] = mapped_column(String(16), default="desktop")
    os: Mapped[str] = mapped_column(String(16), default="other")
    browser: Mapped[str] = mapped_column(String(32), default="Other")
    country: Mapped[str] = mapped_column(String(8), default="Unknown")
    visitor_hash: Mapped[str] = mapped_column(String(64), index=True)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    bot_reason: Mapped[str | None] = mapped_column(String(64))
    destination: Mapped[str | None] = mapped_column(Text)  # which target the visitor was sent to


class BlockedDomain(Base):
    __tablename__ = "blocked_domains"
    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_target", "target_type", "target_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(50), index=True)
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    actor: Mapped[User | None] = relationship()
