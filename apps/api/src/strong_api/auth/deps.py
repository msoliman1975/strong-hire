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
SESSION_EPOCH_KEY = "ep"
SESSION_PENDING_KEY = "pending_signup"

SUSPENDED_MESSAGE = "This account is not available. Contact support for help."
"""AU-7: the same neutral reply for every request and sign-in of a suspended user."""


class AccountSuspendedError(HTTPException):
    """AU-7: the user is suspended. 403 with the neutral message."""

    def __init__(self) -> None:
        super().__init__(status.HTTP_403_FORBIDDEN, SUSPENDED_MESSAGE)


def start_user_session(request: Request, user: User) -> None:
    """Put the user in a fresh session cookie, with their session epoch (AU-8).

    Refuses a suspended user (AU-7) and leaves them signed out."""
    request.session.clear()
    if user.suspended_at is not None:
        raise AccountSuspendedError()
    request.session[SESSION_USER_KEY] = str(user.id)
    request.session[SESSION_EPOCH_KEY] = user.session_epoch or 0


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """One database session per request. Uses the app's sessionmaker when create_app set one
    (tests pass their own), else the default engine."""
    maker = getattr(request.app.state, "sessionmaker", None) or get_sessionmaker()
    async with maker() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]


async def optional_user(request: Request, db: DbSession) -> User | None:
    user_id = request.session.get(SESSION_USER_KEY)
    if not isinstance(user_id, str):
        return None
    user = await get_user(db, user_id)
    if user is None:
        request.session.clear()  # the account was deleted
        return None
    # AU-8: a cookie from before the last forced sign-out is stale. Cookies made before the
    # epoch existed carry none and count as epoch 0, so nobody was signed out at deploy.
    epoch = request.session.get(SESSION_EPOCH_KEY, 0)
    if not isinstance(epoch, int) or epoch != (user.session_epoch or 0):
        request.session.clear()
        return None
    if user.suspended_at is not None:  # AU-7
        request.session.clear()
        raise AccountSuspendedError()
    if user.email_verified_at is None and user.password_hash is not None:
        # AC-4: a password account counts as signed out until its email is confirmed, also
        # with a cookie from before that rule.
        request.session.clear()
        return None
    return user


async def require_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in first")
    return user


CurrentUser = Annotated[User, Depends(require_user)]
