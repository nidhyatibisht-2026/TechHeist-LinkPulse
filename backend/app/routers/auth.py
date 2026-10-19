# No `from __future__ import annotations` here: slowapi's @limiter.limit wraps endpoints, and
# FastAPI would then resolve string annotations against slowapi's globals, not this module's.

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.db import get_session
from app.models import User
from app.ratelimit import limiter
from app.schemas import LoginIn, RegisterIn, TokenOut, UserOut
from app.security import create_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, name=u.name, role=u.role, is_active=u.is_active, created_at=u.created_at)


@router.post("/register", response_model=TokenOut)
@limiter.limit("10/hour")
async def register(request: Request, data: RegisterIn, session: AsyncSession = Depends(get_session)):
    if await session.scalar(select(User.id).where(User.email == data.email)):
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    # The very first account becomes the admin, so a fresh deployment is manageable.
    is_first = (await session.scalar(select(func.count(User.id)))) == 0
    user = User(email=data.email, name=data.name.strip(), role="admin" if is_first else "user",
                password_hash=await run_in_threadpool(hash_password, data.password))
    session.add(user)
    await session.commit()
    return TokenOut(token=create_token(user), user=user_out(user))


@router.post("/login", response_model=TokenOut)
@limiter.limit("20/10minutes")
async def login(request: Request, data: LoginIn, session: AsyncSession = Depends(get_session)):
    user = await session.scalar(select(User).where(User.email == data.email.strip().lower()))
    ok = user is not None and await run_in_threadpool(verify_password, data.password, user.password_hash)
    if not ok:
        raise HTTPException(401, "Email or password is incorrect.")
    if not user.is_active:
        raise HTTPException(403, "This account has been deactivated.")
    return TokenOut(token=create_token(user), user=user_out(user))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user_out(user)
