"""SM-3: when an admin-started AI candidate run may start (strong_core.sim.check_sim_gate)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from strong_core import runtime_settings as rs
from strong_core import sim
from strong_core.config import get_settings
from strong_core.db.models import Base, InterviewSession, Org, User
from strong_core.gateway import get_gateway
from strong_core.schemas.enums import (
    AuthProvider,
    Difficulty,
    InterviewType,
    Mode,
    SessionStatus,
)

SIM_EMAIL = "sim@example.com"
NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


@compiles(JSONB, "sqlite")
def _jsonb_on_sqlite(type_: Any, compiler: Any, **kw: Any) -> str:
    return "JSON"


@pytest.fixture(autouse=True)
def _sim_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SIM_ENABLED", "true")
    monkeypatch.setenv("SIM_EMAIL", SIM_EMAIL)
    get_settings.cache_clear()
    rs.clear_cache()
    yield
    get_settings.cache_clear()
    rs.clear_cache()


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def _user(db: AsyncSession, email: str) -> uuid.UUID:
    org = Org(name=email)
    db.add(org)
    await db.flush()
    db.add(User(org_id=org.id, email=email, auth_provider=AuthProvider.EMAIL))
    await db.flush()
    return org.id


async def _session(
    db: AsyncSession, org_id: uuid.UUID, started: datetime | None, minutes: int = 30
) -> None:
    db.add(
        InterviewSession(
            org_id=org_id,
            job_target_id=uuid.uuid4(),
            type=InterviewType.BEHAVIORAL,
            difficulty=Difficulty.REALISTIC,
            mode=Mode.REALISTIC,
            duration_min=minutes,
            status=SessionStatus.IN_PROGRESS,
            started_at=started,
        )
    )
    await db.flush()


async def test_live_real_sessions_skips_the_sim_org_and_stuck_sessions(db: AsyncSession) -> None:
    """SM-3: only real users' sessions count, and a session stuck past its length + 15 min not."""
    sim_org = await _user(db, SIM_EMAIL)
    real_org = await _user(db, "real@example.com")
    await _session(db, sim_org, NOW - timedelta(minutes=5))
    await _session(db, real_org, NOW - timedelta(minutes=5))
    await _session(db, real_org, None)  # joined, not started yet
    await _session(db, real_org, NOW - timedelta(minutes=46), minutes=30)  # stuck (AI-1)
    assert await sim.sim_org_id(db) == sim_org
    assert await sim.live_real_sessions(db, now=NOW) == 2


async def test_gate_waits_while_the_live_session_limit_is_reached(db: AsyncSession) -> None:
    """SM-3, D-17: 3 live real sessions by default; the run waits (retry) rather than fails."""
    real_org = await _user(db, "real@example.com")
    for _ in range(2):
        await _session(db, real_org, datetime.now(UTC))
    assert (await sim.check_sim_gate(db, 0.1, get_gateway())).ok

    await _session(db, real_org, datetime.now(UTC))
    gate = await sim.check_sim_gate(db, 0.1, get_gateway())
    assert not gate.ok and gate.retry and gate.reason and "3 real interviews" in gate.reason

    await rs.set(db, rs.SettingKey.SIM_MAX_LIVE_SESSIONS, 0, actor="a@example.com")
    rs.clear_cache()
    assert (await sim.check_sim_gate(db, 0.1, get_gateway())).ok  # 0: no limit


async def test_gate_fails_when_paused_or_off(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SM-3, SM-15: paused or SIM_ENABLED off fails the run; it does not wait."""
    await rs.set(db, rs.SettingKey.SIM_PAUSED, True, actor="a@example.com")
    rs.clear_cache()
    gate = await sim.check_sim_gate(db, 0.1, get_gateway())
    assert not gate.ok and not gate.retry and gate.reason and "paused" in gate.reason

    monkeypatch.setenv("SIM_ENABLED", "false")
    get_settings.cache_clear()
    gate = await sim.check_sim_gate(db, 0.1, get_gateway())
    assert not gate.ok and not gate.retry and gate.reason and "SIM_ENABLED" in gate.reason


async def test_gate_fails_when_the_budget_left_is_too_small(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SM-3: the estimate must fit what is left of today's sim budget."""

    async def budget(_: Any) -> sim.KeyBudget:
        return sim.KeyBudget(spend_usd=4.9, max_budget_usd=5.0, resets_at=None)

    monkeypatch.setattr(sim, "sim_key_budget", budget)
    assert (await sim.check_sim_gate(db, 0.05, get_gateway())).ok
    gate = await sim.check_sim_gate(db, 0.25, get_gateway())
    assert not gate.ok and not gate.retry and gate.reason and "$0.10 left" in gate.reason
