from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _utc(v: datetime | None) -> datetime | None:
    """Treat timezone-less input as UTC. The frontend always sends ISO strings with 'Z'."""
    if v is None:
        return None
    return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)


# ---------- auth ----------
class RegisterIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=72)  # bcrypt ignores bytes past 72
    name: str = Field(default="", max_length=120)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Enter a valid email address.")
        return v


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    is_active: bool
    created_at: datetime


class TokenOut(BaseModel):
    token: str
    user: UserOut


# ---------- links ----------
class TargetIn(BaseModel):
    kind: Literal["device", "os", "country"]
    value: str = Field(min_length=1, max_length=32)
    destination: str = Field(min_length=1, max_length=2048)
    priority: int = 0

    @field_validator("value")
    @classmethod
    def check_value(cls, v: str, info) -> str:
        v = v.strip()
        kind = info.data.get("kind")
        if kind == "device" and v.lower() not in ("mobile", "tablet", "desktop"):
            raise ValueError("Device must be mobile, tablet or desktop.")
        if kind == "os" and v.lower() not in ("ios", "android", "windows", "macos", "linux"):
            raise ValueError("OS must be ios, android, windows, macos or linux.")
        if kind == "country":
            if len(v) != 2 or not v.isalpha():
                raise ValueError("Country must be a 2-letter code such as IN or US.")
            return v.upper()
        return v.lower()


class UtmIn(BaseModel):
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_term: str | None = None
    utm_content: str | None = None


class LinkBase(BaseModel):
    title: str = Field(default="", max_length=200)
    campaign_id: int | None = None
    tag_ids: list[int] = Field(default_factory=list)
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    expired_url: str | None = Field(default=None, max_length=2048)
    click_cap: int | None = Field(default=None, ge=1, le=10_000_000)
    targets: list[TargetIn] = Field(default_factory=list, max_length=20)

    @field_validator("starts_at", "expires_at")
    @classmethod
    def normalize_times(cls, v: datetime | None) -> datetime | None:
        return _utc(v)


class LinkCreate(LinkBase):
    destination: str = Field(min_length=1, max_length=2048)
    alias: str | None = Field(default=None, max_length=50)
    password: str | None = Field(default=None, min_length=4, max_length=72)
    utm: UtmIn | None = None


class LinkUpdate(BaseModel):
    """PATCH: only fields that are sent are changed (model_dump(exclude_unset=True))."""
    destination: str | None = Field(default=None, max_length=2048)
    title: str | None = Field(default=None, max_length=200)
    campaign_id: int | None = None
    tag_ids: list[int] | None = None
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    expired_url: str | None = None
    click_cap: int | None = Field(default=None, ge=1)
    targets: list[TargetIn] | None = None
    password: str | None = Field(default=None, min_length=4, max_length=72)
    remove_password: bool = False
    status: Literal["active", "paused"] | None = None

    @field_validator("starts_at", "expires_at")
    @classmethod
    def normalize_times(cls, v: datetime | None) -> datetime | None:
        return _utc(v)


class ValidateIn(BaseModel):
    destination: str = ""
    alias: str | None = None
    link_id: int | None = None  # when editing, the link's own alias is not a duplicate


class SimulateIn(BaseModel):
    device: Literal["mobile", "tablet", "desktop"] = "desktop"
    os: Literal["ios", "android", "windows", "macos", "linux", "other"] = "other"
    country: str | None = Field(default=None, max_length=2)
    password_ok: bool = False
    at: datetime | None = None

    @field_validator("at")
    @classmethod
    def normalize_at(cls, v: datetime | None) -> datetime | None:
        return _utc(v)


# ---------- campaigns / tags ----------
class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    utm_source: str | None = Field(default=None, max_length=100)
    utm_medium: str | None = Field(default=None, max_length=100)
    utm_campaign: str | None = Field(default=None, max_length=100)


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    color: str = Field(default="#0B7FB5", pattern=r"^#[0-9A-Fa-f]{6}$")


# ---------- admin ----------
class DisableIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class BlockIn(BaseModel):
    domain: str = Field(min_length=3, max_length=255)
    reason: str = Field(default="", max_length=500)
    disable_existing: bool = False


class RoleIn(BaseModel):
    role: Literal["user", "admin"]


# ---------- import ----------
class ImportRow(BaseModel):
    row: int
    destination: str
    alias: str | None = None
    title: str = ""
    campaign: str | None = None
    tags: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    expires_invalid: bool = False
    click_cap: int | None = None


class ImportCommitIn(BaseModel):
    rows: list[ImportRow] = Field(max_length=1000)
