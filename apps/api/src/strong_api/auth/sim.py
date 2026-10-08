"""Sign-in for the AI candidate (P13). Not for people.

    POST /auth/sim-login   header X-Sim-Token: <SIM_TOKEN>
    GET  /auth/sim-budget  the AI-to-AI daily budget: limit, server spend, sim-side spend, left
    POST /auth/sim-spend   the sim reports what its own candidate and judge calls cost

The budget routes answer 404 to everyone except the signed-in sim user. Server spend comes from
the sim's LiteLLM key (SIM_LITELLM_KEY), which also enforces the limit on the server side. The
sim-side spend is kept in Redis for 3 days.

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
from datetime import UTC, datetime, timedelta
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.auth.deps import SESSION_USER_KEY, DbSession, require_user
from strong_api.auth.settings import AuthSettings, get_auth_settings
from strong_api.auth.users import create_user, find_user, normalize_email
from strong_core.config import get_settings
from strong_core.db.models import User
from strong_core.gateway import get_gateway
from strong_core.schemas import AuthProvider
from strong_core.sim import sim_key_budget

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


class SpendStore(Protocol):
    async def add(self, usd: float, at: float) -> None: ...

    async def since(self, start: float) -> float: ...


class RedisSpendStore:
    """Sim-side spend entries in one sorted set, scored by time."""

    KEY = "sim:spend"
    KEEP_S = 3 * 86400

    def __init__(self, url: str) -> None:
        self.url = url

    async def add(self, usd: float, at: float) -> None:
        client = Redis.from_url(self.url)
        try:
            await client.zadd(self.KEY, {f"{uuid.uuid4().hex}:{usd:.6f}": at})
            await client.zremrangebyscore(self.KEY, 0, at - self.KEEP_S)
        finally:
            await client.aclose()

    async def since(self, start: float) -> float:
        client = Redis.from_url(self.url)
        try:
            members = await client.zrangebyscore(self.KEY, start, "+inf")
        finally:
            await client.aclose()
        return sum(float(m.split(b":")[1]) for m in members)


class MemorySpendStore:
    """For tests."""

    def __init__(self) -> None:
        self.entries: list[tuple[float, float]] = []

    async def add(self, usd: float, at: float) -> None:
        self.entries.append((at, usd))

    async def since(self, start: float) -> float:
        return sum(usd for at, usd in self.entries if at >= start)


def _spend_store(request: Request) -> SpendStore:
    store: SpendStore | None = getattr(request.app.state, "sim_spend_store", None)
    if store is None:
        store = RedisSpendStore(get_settings().redis_url)
        request.app.state.sim_spend_store = store
    return store


class SimBudget(BaseModel):
    limit_usd: float
    server_usd: float | None = Field(description="Interviewer, planner, scorer; None if unknown.")
    sim_usd: float = Field(description="Candidate and judge, as the sim reported them.")
    total_usd: float
    remaining_usd: float
    period_start: datetime
    resets_at: datetime | None


class SimSpend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    usd: float = Field(ge=0, le=100)


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


async def is_sim_user(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """True when sim is on and this user is the sim user. False for every real person."""
    settings = get_auth_settings()
    if not settings.sim_active:
        return False
    user = await db.get(User, user_id)
    return user is not None and normalize_email(user.email) == normalize_email(settings.sim_email)


async def _sim_user(db: DbSession, user: Annotated[User, Depends(require_user)]) -> User:
    if not await is_sim_user(db, user.id):
        raise _not_found()
    return user


SimUser = Annotated[User, Depends(_sim_user)]


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
        user.last_sign_in_at = datetime.now(UTC)
        await db.commit()
        request.session.clear()
        request.session[SESSION_USER_KEY] = str(user.id)
        log.info("sim-login ok from %s", client)

    @router.get("/sim-budget")
    async def sim_budget(request: Request, _: SimUser) -> SimBudget:
        key = await sim_key_budget(get_gateway())
        now = datetime.now(UTC)
        resets_at = key.resets_at if key else None
        start = resets_at - timedelta(days=1) if resets_at else now - timedelta(days=1)
        limit = (key.max_budget_usd if key else None) or settings.sim_daily_budget_usd
        sim_usd = await _spend_store(request).since(start.timestamp())
        server_usd = key.spend_usd if key else None
        total = (server_usd or 0.0) + sim_usd
        return SimBudget(
            limit_usd=limit,
            server_usd=server_usd,
            sim_usd=round(sim_usd, 6),
            total_usd=round(total, 6),
            remaining_usd=round(max(0.0, limit - total), 6),
            period_start=start,
            resets_at=resets_at,
        )

    @router.post("/sim-spend", status_code=status.HTTP_204_NO_CONTENT)
    async def sim_spend(request: Request, body: SimSpend, _: SimUser) -> None:
        await _spend_store(request).add(body.usd, datetime.now(UTC).timestamp())

    return router
