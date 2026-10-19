"""Small server-rendered pages visitors see instead of a redirect. All values are HTML-escaped."""
from __future__ import annotations

from html import escape

from fastapi.responses import HTMLResponse

_CSS = """
:root{--ink:#16233A;--paper:#F3F6F8;--line:#D8E0E7;--muted:#5B6B7E;--pulse:#0B7FB5;--bad:#B4362A}
@media (prefers-color-scheme:dark){:root{--ink:#E6EDF3;--paper:#0F1722;--line:#2A3A4E;--muted:#93A3B5;--pulse:#4FB3E3;--bad:#F07A6E}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--paper);
color:var(--ink);font:16px/1.55 "IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;padding:24px}
main{max-width:420px;width:100%}.mark{display:flex;gap:4px;align-items:flex-end;height:22px;margin-bottom:28px}
.mark span{width:4px;background:var(--pulse);border-radius:2px}h1{font-size:1.6rem;line-height:1.2;margin:0 0 8px}
p{color:var(--muted);margin:0 0 20px}label{display:block;font-weight:600;margin-bottom:6px}
input{width:100%;padding:12px 14px;font:inherit;border:1px solid var(--line);border-radius:8px;background:transparent;color:var(--ink)}
input:focus{outline:2px solid var(--pulse);outline-offset:1px}
button{margin-top:14px;width:100%;padding:12px;font:inherit;font-weight:600;border:0;border-radius:8px;background:var(--pulse);color:#fff;cursor:pointer}
button:focus-visible{outline:2px solid var(--ink);outline-offset:2px}.err{color:var(--bad);font-weight:600;margin:12px 0 0}
small{display:block;margin-top:32px;color:var(--muted)}
"""

_MARK = '<div class="mark" aria-hidden="true">' + "".join(
    f'<span style="height:{h}px"></span>' for h in (6, 12, 22, 9, 16, 5)) + "</div>"


def _page(title: str, body: str, status: int = 200, extra_head: str = "") -> HTMLResponse:
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>{escape(title)}</title>{extra_head}<style>{_CSS}</style></head>
<body><main>{_MARK}{body}<small>Short link by LinkPulse</small></main></body></html>"""
    return HTMLResponse(html, status_code=status, headers={"Cache-Control": "no-store"})


def message(action: str, detail: str = "") -> HTMLResponse:
    pages = {
        "not_found": ("Link not found", "Check the address for typos. Short links are not case-sensitive.", 404),
        "blocked": ("This link has been disabled", "It was turned off for safety reasons and no longer redirects.", 403),
        "paused": ("This link is paused", "The owner has paused this link. Try again later.", 404),
        "not_started": ("This link is not live yet", "It has been scheduled and will start working soon.", 404),
        "expired": ("This link has expired", "The owner set an end date for this link, and it has passed.", 410),
        "limit": ("This link has reached its limit", "It was set to work for a fixed number of visits, and all have been used.", 410),
        "rate_limited": ("Too many attempts", "Wait a few minutes before trying the password again.", 429),
    }
    title, text, status = pages.get(action, pages["not_found"])
    return _page(title, f"<h1>{escape(title)}</h1><p>{escape(text)}</p>", status)


def password_form(code: str, query: str, error: bool) -> HTMLResponse:
    action = f"/{escape(code)}" + (f"?{escape(query)}" if query else "")
    err = '<p class="err" role="alert">That password is incorrect.</p>' if error else ""
    body = f"""<h1>This link is protected</h1><p>Enter the password the link owner shared with you.</p>
<form method="post" action="{action}"><label for="pw">Password</label>
<input id="pw" name="password" type="password" autocomplete="current-password" required autofocus>
{err}<button type="submit">Open link</button></form>"""
    return _page("Protected link", body, 401 if error else 200)


def preview(title: str) -> HTMLResponse:
    """Served to link-preview bots on capped links: a title card, but no destination and no click used."""
    t = escape(title or "Shared link")
    head = f'<meta property="og:title" content="{t}"><meta property="og:site_name" content="LinkPulse">'
    return _page(t, f"<h1>{t}</h1><p>Open this link in a browser to continue.</p>", 200, head)
