"""User-agent parsing and bot detection.

Why our own small parser instead of a library: the SAME function is used in the
redirect path (for device/OS targeting) and in the click worker (for analytics),
so targeting and reports can never disagree. It is also pure and unit-tested.
It is deliberately simple; swap in `ua-parser` later if you need more detail.

Bot detection returns a REASON, not just True/False, so the UI can show *why*
a click was filtered. Link-preview fetchers (WhatsApp, Slack, Telegram...) are
the important case: they fetch a link the moment it is pasted into a chat, so
without filtering they inflate click counts and can burn through a click cap
before any human has clicked.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

_BOT_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"facebookexternalhit|facebot|twitterbot|slackbot|slack-imgproxy|whatsapp|"
                r"telegrambot|discordbot|linkedinbot|skypeuripreview|pinterestbot|redditbot|"
                r"embedly|iframely|vkshare|viber|snapchat|google-pagerenderer|bitlybot", re.I),
     "link preview fetcher"),
    (re.compile(r"googlebot|bingbot|yandex(bot|images)|baiduspider|duckduckbot|applebot|"
                r"ahrefsbot|semrushbot|mj12bot|petalbot|bytespider|gptbot|ccbot|claudebot|"
                r"perplexitybot|amazonbot|dotbot|seznambot", re.I),
     "search or AI crawler"),
    (re.compile(r"headlesschrome|phantomjs|puppeteer|playwright|selenium|lighthouse", re.I),
     "headless browser"),
    (re.compile(r"^curl/|^wget/|python-requests|python-httpx|python-urllib|aiohttp|"
                r"go-http-client|^java/|okhttp|axios|node-fetch|undici|libwww-perl|scrapy|"
                r"httpclient|postmanruntime|insomnia", re.I),
     "scripted client"),
    (re.compile(r"(?<!cu)bot\b|crawl|spider|scraper|monitor|uptime|preview", re.I),
     "generic bot signature"),
]

_PREFETCH_HEADERS = ("purpose", "sec-purpose", "x-purpose", "x-moz")


def detect_bot(user_agent: str | None, headers: Mapping[str, str] | None = None) -> tuple[bool, str | None]:
    ua = (user_agent or "").strip()
    if not ua:
        return True, "missing user agent"
    for pattern, reason in _BOT_RULES:
        if pattern.search(ua):
            return True, reason
    if headers:
        for h in _PREFETCH_HEADERS:
            value = headers.get(h)
            if value and ("prefetch" in value.lower() or "preview" in value.lower()):
                return True, "browser prefetch"
    return False, None


@dataclass(frozen=True)
class Agent:
    device: str   # mobile | tablet | desktop
    os: str       # ios | android | windows | macos | linux | other
    browser: str  # Chrome | Safari | Firefox | Edge | Opera | Samsung Internet | Other


def parse_agent(user_agent: str | None) -> Agent:
    ua = user_agent or ""

    # Operating system (order matters: iPad/iPhone UAs contain "like Mac OS X")
    if re.search(r"iphone|ipad|ipod", ua, re.I):
        os_name = "ios"
    elif re.search(r"android", ua, re.I):
        os_name = "android"
    elif re.search(r"windows", ua, re.I):
        os_name = "windows"
    elif re.search(r"macintosh|mac os x", ua, re.I):
        os_name = "macos"
    elif re.search(r"linux|x11|cros", ua, re.I):
        os_name = "linux"
    else:
        os_name = "other"

    # Device
    if re.search(r"ipad|tablet", ua, re.I) or (os_name == "android" and not re.search(r"mobile", ua, re.I)):
        device = "tablet"
    elif re.search(r"mobi|iphone|ipod|android", ua, re.I):
        device = "mobile"
    else:
        device = "desktop"

    # Browser (order matters: Edge and Opera UAs also contain "Chrome")
    if re.search(r"edg(e|a|ios)?/", ua, re.I):
        browser = "Edge"
    elif re.search(r"opr/|opera", ua, re.I):
        browser = "Opera"
    elif re.search(r"samsungbrowser", ua, re.I):
        browser = "Samsung Internet"
    elif re.search(r"firefox/|fxios/", ua, re.I):
        browser = "Firefox"
    elif re.search(r"chrome/|crios/|chromium/", ua, re.I):
        browser = "Chrome"
    elif re.search(r"safari/", ua, re.I) and re.search(r"version/", ua, re.I):
        browser = "Safari"
    else:
        browser = "Other"

    return Agent(device=device, os=os_name, browser=browser)
