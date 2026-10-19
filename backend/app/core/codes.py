"""Short-code generation and alias validation.

Design decision: codes are CASE-INSENSITIVE. Everything is stored and looked up
in lowercase, so `Promo` and `promo` can never be two different links (a common
source of confusion when people type links from posters or QR fallbacks).

Generated codes use a 36-character alphabet (0-9, a-z). At length 7 that is
36**7 ~= 78 billion combinations, so random collisions are rare; when one does
happen the database's unique index rejects it and we retry with a new code.

Pure module: standard library only, so it can be unit-tested without a database.
"""
from __future__ import annotations

import re
import secrets
import string

ALPHABET = string.digits + string.ascii_lowercase
DEFAULT_LENGTH = 7

# 3-50 chars, starts and ends with a letter/digit, may contain - and _ inside.
ALIAS_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{1,48})[a-z0-9]$")

# Anything that is (or may become) one of our own routes cannot be an alias,
# otherwise a user could shadow /api, /docs, /health ... with a redirect.
RESERVED = frozenset(
    {
        "api", "admin", "docs", "redoc", "health", "login", "logout", "register",
        "signup", "static", "assets", "app", "dashboard", "settings", "account",
        "qr", "www", "help", "about", "terms", "privacy", "links", "link", "new",
        "import", "analytics", "campaigns", "tags", "users", "blocked", "expired",
        "favicon", "robots", "sitemap", "status", "linkpulse",
    }
)


def generate_code(length: int = DEFAULT_LENGTH) -> str:
    """Cryptographically random code. `secrets` (not `random`) so codes are not guessable."""
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def normalize_alias(alias: str | None) -> str | None:
    if alias is None:
        return None
    alias = alias.strip().lower()
    return alias or None


def alias_problems(alias: str) -> list[str]:
    """Return human-readable problems with an alias (empty list = valid format).

    Uniqueness is NOT checked here because it needs the database.
    """
    problems: list[str] = []
    if len(alias) < 3:
        problems.append("Alias must be at least 3 characters.")
    elif len(alias) > 50:
        problems.append("Alias must be 50 characters or fewer.")
    elif not ALIAS_RE.match(alias):
        problems.append(
            "Use only letters, numbers, hyphens and underscores, "
            "starting and ending with a letter or number."
        )
    if alias in RESERVED:
        problems.append(f"'{alias}' is reserved by LinkPulse. Choose a different alias.")
    return problems


# Anything that could possibly be a code; used to reject junk paths before any lookup.
LOOKUP_RE = re.compile(r"^[a-z0-9_-]{3,50}$")


def is_lookup_candidate(code: str) -> bool:
    return bool(LOOKUP_RE.match(code))
