"""URL validation helpers (pure; DNS and HTTP checks live in services/safety.py).

Each problem is an Issue with a severity:
  error   -> blocks publishing
  warning -> shown in the wizard's review step; user may publish anyway
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, asdict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MAX_URL_LENGTH = 2048


@dataclass
class Issue:
    field: str
    code: str
    message: str
    severity: str = "error"

    def as_dict(self) -> dict:
        return asdict(self)


def normalize_url(raw: str) -> str:
    """Trim whitespace and add https:// when the scheme is missing ("example.com/x")."""
    url = (raw or "").strip()
    if url and "://" not in url and not url.lower().startswith(("javascript:", "data:", "mailto:", "file:")):
        url = "https://" + url
    return url


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def domain_suffixes(host: str) -> list[str]:
    """login.evil.com -> [login.evil.com, evil.com]. Blocking evil.com blocks its subdomains."""
    parts = host.lower().strip(".").split(".")
    return [".".join(parts[i:]) for i in range(len(parts) - 1)] or ([host] if host else [])


def blocked_match(host: str, blocked: set[str]) -> str | None:
    for suffix in domain_suffixes(host):
        if suffix in blocked:
            return suffix
    return None


def is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
                or addr.is_multicast or addr.is_unspecified)


def url_issues(url: str, field: str, own_hosts: set[str]) -> list[Issue]:
    """Static checks that need no network access."""
    issues: list[Issue] = []
    if not url:
        return [Issue(field, "required", "Enter a destination URL.")]
    if len(url) > MAX_URL_LENGTH:
        issues.append(Issue(field, "too_long", f"URL is longer than {MAX_URL_LENGTH} characters."))
    try:
        parts = urlsplit(url)
    except ValueError:
        return [Issue(field, "invalid", "This is not a valid URL.")]

    if parts.scheme.lower() not in ("http", "https"):
        # Blocks javascript:, data:, file: and similar schemes used in attacks.
        issues.append(Issue(field, "scheme", "Only http:// and https:// links are allowed."))
        return issues

    host = (parts.hostname or "").lower()
    if not host:
        issues.append(Issue(field, "no_host", "The URL is missing a domain name."))
        return issues
    if parts.username or parts.password:
        issues.append(Issue(field, "credentials",
                            "URLs with a username or password before the domain are not allowed "
                            "(a common phishing trick)."))
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        issues.append(Issue(field, "private", "Links to local or internal addresses are not allowed."))
    else:
        try:
            ipaddress.ip_address(host)
            is_ip = True
        except ValueError:
            is_ip = False
        if is_ip and not is_public_ip(host):
            issues.append(Issue(field, "private", "Links to private network addresses are not allowed."))
        elif not is_ip and "." not in host:
            issues.append(Issue(field, "no_tld", "The domain needs an extension such as .com or .in."))
    if host in own_hosts:
        issues.append(Issue(field, "loop", "This URL points back to LinkPulse and would create a redirect loop."))

    if parts.scheme.lower() == "http":
        issues.append(Issue(field, "insecure", "This link is not encrypted (http). Use https if the site supports it.",
                            "warning"))
    if any(label.startswith("xn--") for label in host.split(".")):
        issues.append(Issue(field, "punycode",
                            "This domain uses international characters. Check it is not a look-alike of a "
                            "well-known site.", "warning"))
    return issues


def add_utm(url: str, params: dict[str, str | None]) -> str:
    """Merge utm_* parameters into a URL, keeping existing query parameters."""
    clean = {k: v.strip() for k, v in params.items() if v and v.strip()}
    if not clean:
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(clean)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def referrer_domain(referrer: str | None) -> str:
    if not referrer:
        return "Direct"
    host = host_of(referrer)
    if host.startswith("www."):
        host = host[4:]
    return host or "Direct"
