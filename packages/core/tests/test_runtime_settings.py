"""OC-1..OC-5: typed runtime settings with a 10 s in-process cache."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from strong_core import runtime_settings as rs
from strong_core.db.models import Base, RuntimeSetting


@compiles(JSONB, "sqlite")
def _jsonb_on_sqlite(type_: Any, compiler: Any, **kw: Any) -> str:
    return "JSON"


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all, tables=[Base.metadata.tables["runtime_settings"]]
        )
    rs.clear_cache()
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    rs.clear_cache()
    await engine.dispose()


async def test_defaults_without_rows(db: AsyncSession) -> None:
    """OC-1..OC-5 defaults; D-6: the daily spend cap is $25."""
    current = await rs.get_all(db)
    assert current.signups_paused is False
    assert current.sessions_paused_voice is False
    assert current.sessions_paused_text is False
    assert current.daily_spend_cap_usd == 25.0
    assert current.site_banner is None
    assert current.jobs_paused == []
    assert set(rs.KEYS) == set(rs.RuntimeSettings.model_fields)


async def test_set_validates_writes_and_reads_back(db: AsyncSession) -> None:
    """OC-1, OC-2, OC-3, OC-5."""
    assert await rs.set(db, rs.SettingKey.SIGNUPS_PAUSED, True, actor="a@example.com") is True
    await rs.set(db, "sessions_paused_voice", True, actor="a@example.com")
    await rs.set(db, "daily_spend_cap_usd", 40, actor="a@example.com")
    await rs.set(db, "jobs_paused", ["scoring"], actor="a@example.com")
    await db.commit()

    assert await rs.get(db, "signups_paused") is True
    assert await rs.get(db, "sessions_paused_voice") is True
    assert await rs.get(db, "sessions_paused_text") is False
    assert await rs.get(db, "daily_spend_cap_usd") == 40.0
    assert await rs.get(db, "jobs_paused") == [rs.JobKind.SCORING]

    row = await db.get(RuntimeSetting, "jobs_paused")
    assert row is not None and row.value_json == ["scoring"] and row.updated_by == "a@example.com"


async def test_site_banner_round_trip(db: AsyncSession) -> None:
    """OC-4: text, severity and end time; null clears it."""
    until = datetime(2026, 11, 30, 12, tzinfo=UTC)
    banner = {"text": "Maintenance at noon", "severity": "warning", "until": until.isoformat()}
    await rs.set(db, "site_banner", banner, actor="a@example.com")
    got = await rs.get(db, "site_banner")
    assert isinstance(got, rs.SiteBanner)
    assert got.severity == "warning" and got.until == until
    assert got.active(until - timedelta(minutes=1)) and not got.active(until)

    await rs.set(db, "site_banner", None, actor="a@example.com")
    assert await rs.get(db, "site_banner") is None


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("daily_spend_cap_usd", -1),
        ("jobs_paused", ["email"]),
        ("site_banner", {"text": "x", "severity": "loud", "until": "2026-11-30T00:00:00Z"}),
        ("site_banner", {"text": "", "severity": "info", "until": "2026-11-30T00:00:00Z"}),
        ("signups_paused", "maybe"),
    ],
)
async def test_set_rejects_invalid_values(db: AsyncSession, key: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        await rs.set(db, key, value, actor="a@example.com")
    assert (await db.execute(select(RuntimeSetting))).first() is None


async def test_unknown_key_is_refused(db: AsyncSession) -> None:
    with pytest.raises(rs.UnknownSettingError):
        await rs.set(db, "model_profile", "hosted", actor="a@example.com")
    with pytest.raises(rs.UnknownSettingError):
        await rs.get(db, "model_profile")


async def test_cache_holds_for_ten_seconds(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another process's change shows after the 10 s cache expires."""
    clock = [1000.0]
    monkeypatch.setattr(rs.time, "monotonic", lambda: clock[0])
    assert await rs.get(db, "signups_paused") is False

    # Written behind the helper's back, as another process would.
    db.add(RuntimeSetting(key="signups_paused", value_json=True, updated_by="other"))
    await db.commit()
    clock[0] += 5
    assert await rs.get(db, "signups_paused") is False
    clock[0] += 6
    assert await rs.get(db, "signups_paused") is True


async def test_invalid_stored_value_falls_back_to_default(db: AsyncSession) -> None:
    db.add(RuntimeSetting(key="daily_spend_cap_usd", value_json="lots", updated_by="x"))
    db.add(RuntimeSetting(key="retired_key", value_json=1, updated_by="x"))
    await db.commit()
    assert await rs.get(db, "daily_spend_cap_usd") == 25.0


async def test_sim_settings_defaults_and_bounds(db: AsyncSession) -> None:
    """SM-15, SM-3 (D-17): sim runs are on by default and wait while 3 real sessions are live."""
    current = await rs.get_all(db)
    assert current.sim_paused is False
    assert current.sim_max_live_sessions == 3

    await rs.set(db, rs.SettingKey.SIM_PAUSED, True, actor="a@example.com")
    await rs.set(db, rs.SettingKey.SIM_MAX_LIVE_SESSIONS, 0, actor="a@example.com")
    await db.commit()
    assert await rs.get(db, "sim_paused") is True
    assert await rs.get(db, "sim_max_live_sessions") == 0

    for bad in (-1, 21, "many"):
        with pytest.raises(ValidationError):
            await rs.set(db, rs.SettingKey.SIM_MAX_LIVE_SESSIONS, bad, actor="a@example.com")


def test_cu11_custom_interview_is_open_to_everyone_until_switched() -> None:
    """CU-11: everyone while we test; paid_only when live."""
    assert rs.DEFAULTS.custom_interview_access == rs.CustomInterviewAccess.EVERYONE
    assert rs.validate("custom_interview_access", "paid_only") == rs.CustomInterviewAccess.PAID_ONLY
    with pytest.raises(ValidationError):
        rs.validate("custom_interview_access", "free_only")
