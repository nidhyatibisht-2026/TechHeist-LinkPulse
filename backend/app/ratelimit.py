"""Rate limiting. Shared Redis storage means limits hold across multiple API instances."""
from __future__ import annotations

from fastapi import Request
from slowapi import Limiter

from app.config import settings
from app.security import client_ip, user_id_from_request


def user_or_ip(request: Request) -> str:
    uid = user_id_from_request(request)
    return f"user:{uid}" if uid else f"ip:{client_ip(request)}"


def ip_and_path(request: Request) -> str:
    # Password attempts: limit per visitor per link.
    return f"pw:{client_ip(request)}:{request.url.path}"


limiter = Limiter(key_func=user_or_ip, storage_uri=settings.redis_url or "memory://")
