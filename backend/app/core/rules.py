"""The redirect rule engine.

`evaluate()` is a PURE function: no database, no network, no clock (the time is
passed in). That gives us three things:
  1. It is trivially unit-testable (see tests/test_rules.py).
  2. The Rule Simulator in the UI calls the exact same function, so what you
     see in the simulator is exactly what visitors get.
  3. The rule order lives in one readable place.

RULE ORDER (and why):
  1. exists        - nothing to do without a link
  2. not disabled  - safety first: an admin takedown or blocklisted domain
                     beats every other rule, including expiry fallbacks
  3. not paused    - the owner turned it off
  4. started       - scheduled links are not live yet
  5. not expired   - may send visitors to a fallback URL (Dub-style "expired URL")
  6. under cap     - cheap early rejection from a cached count; the
                     AUTHORITATIVE check is the atomic DB increment that runs
                     after this function returns "redirect"
  7. password      - checked after the cap pre-check, but the click is only
                     consumed after the password succeeds, so wrong guesses
                     never burn clicks
  8. targeting     - choose the destination (device / OS / country rules)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

RULE_ORDER = [
    ("exists", "Link exists"),
    ("safety", "Not disabled or blocklisted"),
    ("paused", "Not paused by owner"),
    ("schedule", "Start time has passed"),
    ("expiry", "Not expired"),
    ("cap", "Under click limit"),
    ("password", "Password accepted"),
    ("targeting", "Destination chosen"),
]

TARGET_KINDS = ("device", "os", "country")
DEVICES = ("mobile", "tablet", "desktop")
OSES = ("ios", "android", "windows", "macos", "linux", "other")


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; treat naive values as UTC everywhere."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class Target:
    kind: str          # "device" | "os" | "country"
    value: str         # e.g. "mobile", "ios", "IN"
    destination: str
    priority: int = 0  # lower runs first


@dataclass
class LinkView:
    """Everything the engine needs to know about a link (a cache-friendly snapshot)."""
    id: int
    code: str
    destination: str
    status: str = "active"            # active | paused | disabled | archived
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    expired_url: str | None = None
    click_cap: int | None = None
    click_count: int = 0
    has_password: bool = False
    targets: list[Target] = field(default_factory=list)


@dataclass
class Visit:
    now: datetime
    device: str = "desktop"
    os: str = "other"
    country: str | None = None
    password_ok: bool = False
    blocked_domain: str | None = None  # set when the destination's domain is blocklisted


@dataclass
class Step:
    rule: str
    passed: bool
    detail: str


@dataclass
class Decision:
    action: str  # redirect | not_found | blocked | paused | not_started | expired | limit | password
    url: str | None = None
    reason: str = ""
    trace: list[Step] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "url": self.url,
            "reason": self.reason,
            "trace": [s.__dict__ for s in self.trace],
        }


def _target_matches(t: Target, visit: Visit) -> bool:
    if t.kind == "device":
        return visit.device == t.value
    if t.kind == "os":
        return visit.os == t.value
    if t.kind == "country":
        return bool(visit.country) and visit.country.upper() == t.value.upper()
    return False


def pick_destination(link: LinkView, visit: Visit) -> tuple[str, str]:
    """First matching target by priority wins; otherwise the default destination."""
    for t in sorted(link.targets, key=lambda t: t.priority):
        if _target_matches(t, visit):
            return t.destination, f"Matched {t.kind} = {t.value}"
    return link.destination, "No targeting rule matched; using default destination"


def evaluate(link: LinkView | None, visit: Visit) -> Decision:
    trace: list[Step] = []

    def stop(rule: str, action: str, detail: str, url: str | None = None) -> Decision:
        trace.append(Step(rule, False, detail))
        return Decision(action=action, url=url, reason=detail, trace=trace)

    # 1. exists
    if link is None or link.status == "archived":
        return stop("exists", "not_found", "No active link uses this code")
    trace.append(Step("exists", True, f"Found /{link.code}"))

    # 2. safety
    if link.status == "disabled":
        return stop("safety", "blocked", "Disabled by an administrator")
    if visit.blocked_domain:
        return stop("safety", "blocked", f"Destination domain {visit.blocked_domain} is blocklisted")
    trace.append(Step("safety", True, "Not disabled; domain not blocklisted"))

    # 3. paused
    if link.status == "paused":
        return stop("paused", "paused", "Paused by the link owner")
    trace.append(Step("paused", True, "Link is live"))

    # 4. schedule
    now = as_utc(visit.now)
    starts = as_utc(link.starts_at)
    if starts and now < starts:
        return stop("schedule", "not_started", f"Goes live at {starts.isoformat()}")
    trace.append(Step("schedule", True, "No start time" if not starts else "Start time has passed"))

    # 5. expiry
    expires = as_utc(link.expires_at)
    if expires and now >= expires:
        if link.expired_url:
            return stop("expiry", "expired", f"Expired at {expires.isoformat()}; sending to fallback URL",
                        url=link.expired_url)
        return stop("expiry", "expired", f"Expired at {expires.isoformat()}")
    trace.append(Step("expiry", True, "No expiry date" if not expires else f"Valid until {expires.isoformat()}"))

    # 6. cap (pre-check; the atomic DB increment is the real guard)
    if link.click_cap is not None and link.click_count >= link.click_cap:
        return stop("cap", "limit", f"Click limit reached ({link.click_count}/{link.click_cap})")
    trace.append(Step("cap", True, "No click limit" if link.click_cap is None
                      else f"{link.click_count}/{link.click_cap} clicks used"))

    # 7. password
    if link.has_password and not visit.password_ok:
        return stop("password", "password", "Password required")
    trace.append(Step("password", True, "No password" if not link.has_password else "Password accepted"))

    # 8. targeting
    url, detail = pick_destination(link, visit)
    trace.append(Step("targeting", True, detail))
    return Decision(action="redirect", url=url, reason=detail, trace=trace)
