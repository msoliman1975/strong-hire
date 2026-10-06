"""FastAPI dependencies for the input endpoints: database session, job queue, current user."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.auth.deps import get_db, require_user
from strong_api.inputs.queue import JobQueue
from strong_core.db.models import User

__all__ = ["CurrentUser", "Db", "Me", "Queue", "current_user", "get_db", "get_queue"]


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    org_id: uuid.UUID


def get_queue(request: Request) -> JobQueue:
    queue: JobQueue = request.app.state.queue
    return queue


async def current_user(user: Annotated[User, Depends(require_user)]) -> CurrentUser:
    """The signed-in user (P3 sign-in). Returns 401 when nobody is signed in.

    Local development signs in with POST /auth/dev-login (APP_ENV=local only).
    """
    return CurrentUser(user_id=user.id, org_id=user.org_id)


Db = Annotated[AsyncSession, Depends(get_db)]
Queue = Annotated[JobQueue, Depends(get_queue)]
Me = Annotated[CurrentUser, Depends(current_user)]
