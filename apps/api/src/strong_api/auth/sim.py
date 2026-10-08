"""Sign-in for the AI candidate (P13). Not for people.

    POST /auth/sim-login   header X-Sim-Token: <SIM_TOKEN>

The route answers 404 unless SIM_ENABLED=true and SIM_TOKEN has 32+ characters, and it answers 404
for a wrong token too, so a scan cannot tell that it exists. After 5 wrong tokens from one address
in 10 minutes, that address gets 404 even with the right token until the window passes. Every
attempt is logged without the token.
"""

from __future__ import annotations

import hmac
import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.auth.deps import SESSION_USER_KEY, DbSession
from strong_api.auth.settings import AuthSettings, get_auth_settings
from strong_api.auth.users import create_user, find_user, normalize_email
from strong_core.db.models import User
from strong_core.schemas import AuthProvider

log = logging.getLogger("strong_api.sim")

MAX_FAILURES = 5
WINDOW_S = 600.0


class FailureLimiter:
    def __init__(self, max_failures: int = MAX_FAILURES, window_s: float = WINDOW_S) -> None:
        self.max_failures = max_failures
        self.window_s = window_s
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _recent(self, key: str) -> deque[float]:
        cutoff = time.monotonic() - self.window_s
        times = self._failures[key]
        while times and times[0] < cutoff:
            times.popleft()
        return times

    def blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= self.max_failures

    def fail(self, key: str) -> None:
        self._recent(key).append(time.monotonic())


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


async def is_sim_user(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """True when sim is on and this user is the sim user. False for every real person."""
    settings = get_auth_settings()
    if not settings.sim_active:
        return False
    user = await db.get(User, user_id)
    return user is not None and normalize_email(user.email) == normalize_email(settings.sim_email)


def build_sim_router(settings: AuthSettings, limiter: FailureLimiter | None = None) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"], include_in_schema=False)
    failures = limiter or FailureLimiter()

    @router.post("/sim-login", status_code=status.HTTP_204_NO_CONTENT)
    async def sim_login(
        request: Request,
        db: DbSession,
        x_sim_token: Annotated[str | None, Header()] = None,
    ) -> None:
        client = request.client.host if request.client else "unknown"
        if not settings.sim_active or settings.sim_token is None:
            raise _not_found()
        if failures.blocked(client):
            log.warning("sim-login refused: too many failures from %s", client)
            raise _not_found()
        expected = settings.sim_token.get_secret_value()
        if not x_sim_token or not hmac.compare_digest(x_sim_token, expected):
            failures.fail(client)
            log.warning("sim-login failed from %s", client)
            raise _not_found()
        email = normalize_email(settings.sim_email)
        user = await find_user(db, email)
        if user is None:
            user = await create_user(
                db,
                email=email,
                provider=AuthProvider.DEV,
                age_confirmed=True,
                terms_accepted=True,
                training_consent=False,
            )
        request.session.clear()
        request.session[SESSION_USER_KEY] = str(user.id)
        log.info("sim-login ok from %s", client)

    return router
