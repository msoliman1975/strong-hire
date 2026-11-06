"""Which sessions are traced (LT-3, LT-7, LT-14): sim org only, dev only when asked, redacted."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import strong_core.sim as sim_module
from strong_core.config import get_settings
from strong_core.db.models import Base, InterviewSession, User
from strong_core.schemas.enums import AuthProvider, Difficulty, InterviewType, Mode
from strong_core.tracing import TraceTags, current_trace_tags, set_exporter_override
from strong_core.tracing.sessions import maybe_trace, parse_trace_settings, trace_tags_for
from strong_core.tracing.testing import InMemoryExporter

SIM_EMAIL = "sim@example.test"
SIM_ORG, REAL_ORG = uuid.uuid4(), uuid.uuid4()


@pytest.fixture
def tracing_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SIM_ENABLED", "true")
    monkeypatch.setenv("SIM_EMAIL", SIM_EMAIL)
    monkeypatch.delenv("LLM_TRACING_DEV", raising=False)
    get_settings.cache_clear()
    sim_module._sim_orgs.clear()
    previous = set_exporter_override(InMemoryExporter())
    yield
    set_exporter_override(previous)
    sim_module._sim_orgs.clear()
    get_settings.cache_clear()


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    """SQLite with users and sessions only. SQLite does not enforce the foreign keys."""
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    tables = [Base.metadata.tables["users"], Base.metadata.tables["sessions"]]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=tables)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add_all(
            [
                User(org_id=SIM_ORG, email=SIM_EMAIL, auth_provider=AuthProvider.EMAIL),
                User(org_id=REAL_ORG, email="jane@example.test", auth_provider=AuthProvider.EMAIL),
            ]
        )
        await session.commit()
        yield session
    await engine.dispose()


async def _session(db: AsyncSession, org: uuid.UUID, trace_json: object = None) -> uuid.UUID:
    row = InterviewSession(
        org_id=org,
        job_target_id=uuid.uuid4(),
        type=InterviewType.BEHAVIORAL,
        difficulty=Difficulty.REALISTIC,
        mode=Mode.REALISTIC,
        duration_min=30,
        trace_json=trace_json,
    )
    db.add(row)
    await db.commit()
    return row.id


async def test_lt3_real_users_session_is_never_traced(tracing_on: None, db: AsyncSession) -> None:
    """LT-3: a real user's session gets no trace tags, even with sim settings stored on it."""
    sid = await _session(db, REAL_ORG, {"sim_run_id": "r", "content": "full"})
    assert await trace_tags_for(org_id=REAL_ORG, session_id=sid, service="api", db=db) is None


async def test_lt3_nothing_when_tracing_is_off(db: AsyncSession) -> None:
    """LT-1, LT-3: with tracing inactive the answer is None, without reading the database."""

    class Exploding:
        def __getattr__(self, name: str) -> object:
            raise AssertionError("the database was read")

    tags = await trace_tags_for(org_id=SIM_ORG, session_id=None, service="api", db=Exploding())  # type: ignore[arg-type]
    assert tags is None


async def test_lt14_sim_session_uses_its_stored_settings(
    tracing_on: None, db: AsyncSession
) -> None:
    """LT-7, LT-14: the sim's run, scenario and content mode become the trace tags."""
    stored = {"sim_run_id": "20261105-run", "scenario": "backend-senior", "content": "full"}
    sid = await _session(db, SIM_ORG, stored)
    tags = await trace_tags_for(org_id=SIM_ORG, session_id=sid, service="worker", db=db)
    assert tags is not None
    assert (tags.sim_run_id, tags.scenario, tags.content) == (
        "20261105-run",
        "backend-senior",
        "full",
    )
    assert tags.session_id == str(sid) and tags.service == "worker"
    assert tags.model_profile == "fake" and tags.release
    assert tags.experiment is None  # MLFLOW_EXPERIMENT (sim on the servers)


async def test_lt14_sim_session_without_or_with_bad_settings_is_redacted(
    tracing_on: None, db: AsyncSession
) -> None:
    """LT-4, LT-14: missing or invalid settings mean redacted."""
    for stored in (None, {"content": "everything"}, {"sim_run_id": "x", "extra": 1}, "full"):
        sid = await _session(db, SIM_ORG, stored)
        tags = await trace_tags_for(org_id=SIM_ORG, session_id=sid, service="api", db=db)
        assert tags is not None and tags.content == "redacted", stored


async def test_lt14_a_session_of_another_org_is_not_read(
    tracing_on: None, db: AsyncSession
) -> None:
    """LT-14: the stored settings are read only when the session belongs to the org."""
    sid = await _session(db, REAL_ORG, {"content": "full"})
    tags = await trace_tags_for(org_id=SIM_ORG, session_id=sid, service="api", db=db)
    assert tags is not None and tags.content == "redacted"


async def test_lt3_dev_flag_traces_any_session_redacted(
    tracing_on: None, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LT-3, D-6: LLM_TRACING_DEV=on traces a developer's sessions, redacted, in dev."""
    monkeypatch.setenv("LLM_TRACING_DEV", "on")
    get_settings.cache_clear()
    sid = await _session(db, REAL_ORG, {"content": "full"})
    tags = await trace_tags_for(org_id=REAL_ORG, session_id=sid, service="api", db=db)
    assert tags is not None
    assert tags.content == "redacted" and tags.experiment == "dev" and tags.sim_run_id is None


async def test_lt3_lookup_failure_means_no_tracing(tracing_on: None) -> None:
    """LT-5: a failing lookup never raises; the call is simply not traced."""

    class Broken:
        async def scalar(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("db down")

    tags = await trace_tags_for(org_id=SIM_ORG, session_id=None, service="api", db=Broken())  # type: ignore[arg-type]
    assert tags is None


def test_lt14_parse_trace_settings() -> None:
    """LT-14: parsing never raises."""
    assert parse_trace_settings({"content": "full"}).content == "full"
    assert parse_trace_settings([1]).content == "redacted"


def test_maybe_trace_sets_the_context_only_with_tags() -> None:
    """LT-3: maybe_trace(None) leaves no trace context."""
    with maybe_trace(None):
        assert current_trace_tags() is None
    tags = TraceTags(session_id="s")
    with maybe_trace(tags):
        assert current_trace_tags() is tags
    assert current_trace_tags() is None
