"""FastAPI dependencies for sign-in. Other routers use `require_user` to get the current user."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.auth.users import get_user
from strong_core.db import get_sessionmaker
from strong_core.db.models import User

SESSION_USER_KEY = "uid"
SESSION_PENDING_KEY = "pending_signup"


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]


async def optional_user(request: Request, db: DbSession) -> User | None:
    user_id = request.session.get(SESSION_USER_KEY)
    if not isinstance(user_id, str):
        return None
    user = await get_user(db, user_id)
    if user is None:
        request.session.clear()  # the account was deleted
    return user


async def require_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in first")
    return user


CurrentUser = Annotated[User, Depends(require_user)]
