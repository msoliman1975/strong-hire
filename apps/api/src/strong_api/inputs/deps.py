"""FastAPI dependencies for the input endpoints: database session, job queue, current user."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_api.inputs.queue import JobQueue
from strong_core.config import get_settings
from strong_core.db.models import Org, User
from strong_core.schemas import AuthProvider, OrgType

DEV_USER_EMAIL = "dev@stronghire.local"


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    org_id: uuid.UUID


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    maker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with maker() as session:
        yield session


def get_queue(request: Request) -> JobQueue:
    queue: JobQueue = request.app.state.queue
    return queue


Db = Annotated[AsyncSession, Depends(get_db)]
Queue = Annotated[JobQueue, Depends(get_queue)]


async def dev_user(db: Db) -> CurrentUser:
    """Accounts arrive with P9. Until then every request acts as one dev user, outside prod only.
    Replace this dependency (app.dependency_overrides) when real sign-in exists."""
    if get_settings().env == "prod":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in is required")
    user = await db.scalar(select(User).where(User.email == DEV_USER_EMAIL))
    if user is None:
        org = Org(name="Dev org", type=OrgType.PERSONAL)
        db.add(org)
        await db.flush()
        user = User(org_id=org.id, email=DEV_USER_EMAIL, auth_provider=AuthProvider.DEV)
        db.add(user)
        await db.commit()
    return CurrentUser(user_id=user.id, org_id=user.org_id)


Me = Annotated[CurrentUser, Depends(dev_user)]
