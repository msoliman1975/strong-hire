"""The sim service (strong-sim serve): admin-started runs, one at a time (SM-2..SM-5, SM-13, SM-14).

SQLite stands in for Postgres, the API is the fake from conftest, the models are the fake backend.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from strong_core import runtime_settings as rs
from strong_core.config import get_settings
from strong_core.db.models import Base, InterviewSession, Org, SimRun, User
from strong_core.gateway import ModelGateway
from strong_core.schemas.enums import (
    AuthProvider,
    Difficulty,
    InterviewType,
    Mode,
    SessionStatus,
    SimRunStatus,
)
from strong_sim import retention
from strong_sim.client import AppClient
from strong_sim.scenarios import Scenario
from strong_sim.serve import SimService
from strong_sim.settings import SimSettings

TOKEN = "t" * 40
SIM_EMAIL = "sim@example.com"


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
async def sessionmaker(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    # A file, not one shared in-memory connection: the service's sessions overlap (the cancel
    # check runs while the session hooks write), and each needs its own connection.
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'sim.db'}", connect_args={"timeout": 30}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def settings(tmp_path: Path) -> SimSettings:
    return SimSettings(
        base_url="https://sim.test/api",
        token=TOKEN,
        out_dir=tmp_path / "sim",
        upload_target="",
        poll_s=0.02,
        progress_every_s=0.02,
    )


class SlowApi:
    """The fake API with a short wait on each candidate turn, so a run can be cancelled."""

    def __init__(self, api: Any, delay_s: float) -> None:
        self.api, self.delay_s = api, delay_s

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/text/turn"):
            await asyncio.sleep(self.delay_s)
        response: httpx.Response = self.api(request)
        return response


def _service(
    settings: SimSettings,
    sessionmaker: async_sessionmaker[AsyncSession],
    gateway: ModelGateway,
    handler: Any,
) -> SimService:
    def client(s: SimSettings) -> AppClient:
        transport = httpx.MockTransport(handler)
        return AppClient(s, httpx.AsyncClient(base_url=s.base_url, transport=transport))

    return SimService(settings, sessionmaker, gateway, client_factory=client)


async def _org(db: AsyncSession, email: str) -> uuid.UUID:
    org = Org(name=email)
    db.add(org)
    await db.flush()
    db.add(User(org_id=org.id, email=email, auth_provider=AuthProvider.EMAIL))
    await db.commit()
    return org.id


async def _queue(sessionmaker: async_sessionmaker[AsyncSession], **fields: Any) -> uuid.UUID:
    async with sessionmaker() as db:
        org_id = await _org(db, f"{uuid.uuid4().hex[:6]}-{SIM_EMAIL}")
        scenario = Scenario(id="admin", channel="text", candidate_name="Ada Venn")
        run = SimRun(
            org_id=org_id,
            scenario_json=scenario.model_dump(mode="json"),
            created_by="admin@example.com",
            **fields,
        )
        db.add(run)
        await db.commit()
        return run.id


async def _get(sessionmaker: async_sessionmaker[AsyncSession], run_id: uuid.UUID) -> SimRun:
    async with sessionmaker() as db:
        run = await db.get(SimRun, run_id)
        assert run is not None
        return run


async def test_a_queued_run_runs_to_done_and_saves_its_folder(
    settings: SimSettings,
    sessionmaker: async_sessionmaker[AsyncSession],
    fake_gateway: ModelGateway,
    fake_api: Any,
) -> None:
    """SM-2, SM-4: queued -> starting -> interviewing -> judging -> done, with the files."""
    api = fake_api(TOKEN)
    service = _service(settings, sessionmaker, fake_gateway, api)
    run_id = await _queue(sessionmaker)

    assert await service.tick() is True
    run = await _get(sessionmaker, run_id)
    assert run.status == SimRunStatus.DONE, run.status_reason
    assert run.status_reason is None and run.started_at and run.finished_at
    assert run.run_dir and run.run_dir.split("-")[2] == "admin"
    (sid,) = api.sessions
    assert str(run.session_id) == sid
    folder = settings.out_dir / run.run_dir
    assert (folder / "scenarios.yaml").exists() and (folder / "report.json").exists()
    meta = json.loads((folder / sid / "meta.json").read_text("utf-8"))
    assert meta["timing"] == "server"  # a text run
    lines = json.loads((folder / sid / "transcript.json").read_text("utf-8"))
    replies = [x for x in lines if x["speaker"] == "interviewer"][1:]
    assert replies and all(x["latency_ms"] is not None for x in replies)  # SM-9 on text runs
    assert api.reported_usd == []  # the sim key's budget counts it; no double count
    assert await service.tick() is False  # nothing left


async def test_cancel_ends_the_session_and_keeps_what_was_said(
    settings: SimSettings,
    sessionmaker: async_sessionmaker[AsyncSession],
    fake_gateway: ModelGateway,
    fake_api: Any,
) -> None:
    """SM-5: an active run ends its session on the server, saves the transcript, no judge."""
    api = fake_api(TOKEN, turns_per_session=500)
    service = _service(settings, sessionmaker, fake_gateway, SlowApi(api, 0.05))
    run_id = await _queue(sessionmaker)
    task = asyncio.create_task(service.tick())
    for _ in range(200):
        if (await _get(sessionmaker, run_id)).status == SimRunStatus.INTERVIEWING:
            break
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.2)
    async with sessionmaker() as db:
        run = await db.get(SimRun, run_id)
        assert run is not None
        run.cancel_requested_at = datetime.now(UTC)
        await db.commit()
    await asyncio.wait_for(task, timeout=10)

    run = await _get(sessionmaker, run_id)
    assert run.status == SimRunStatus.CANCELLED and run.finished_at
    (sid,) = api.sessions
    assert api.sessions[sid]["status"] == "scoring"  # ended on the server
    folder = settings.out_dir / str(run.run_dir) / sid
    assert json.loads((folder / "transcript.json").read_text("utf-8"))
    assert not (folder / "judge.json").exists()


async def test_a_run_cancelled_before_it_starts_never_signs_in(
    settings: SimSettings,
    sessionmaker: async_sessionmaker[AsyncSession],
    fake_gateway: ModelGateway,
    fake_api: Any,
) -> None:
    """SM-5: a queued run with a cancel request ends cancelled at once."""
    api = fake_api(TOKEN)
    service = _service(settings, sessionmaker, fake_gateway, api)
    run_id = await _queue(sessionmaker, cancel_requested_at=datetime.now(UTC))
    await service.tick()
    assert (await _get(sessionmaker, run_id)).status == SimRunStatus.CANCELLED
    assert api.signed_in is False


async def test_a_run_waits_while_real_users_are_live_then_fails_after_the_limit(
    settings: SimSettings,
    sessionmaker: async_sessionmaker[AsyncSession],
    fake_gateway: ModelGateway,
    fake_api: Any,
) -> None:
    """SM-3, D-17: 3 live real sessions -> waiting, checked again later; failed after 30 min."""
    async with sessionmaker() as db:
        real = await _org(db, "real@example.com")
        for _ in range(3):
            db.add(
                InterviewSession(
                    org_id=real, job_target_id=uuid.uuid4(), type=InterviewType.BEHAVIORAL,
                    difficulty=Difficulty.REALISTIC, mode=Mode.REALISTIC, duration_min=30,
                    status=SessionStatus.IN_PROGRESS, started_at=datetime.now(UTC),
                )
            )  # fmt: skip
        await db.commit()
    api = fake_api(TOKEN)
    service = _service(settings, sessionmaker, fake_gateway, api)
    run_id = await _queue(sessionmaker)

    await service.tick()
    run = await _get(sessionmaker, run_id)
    assert run.status == SimRunStatus.WAITING
    assert run.status_reason and "3 real interviews are live" in run.status_reason
    assert await service.tick() is False  # not checked again until wait_recheck_s
    assert api.sessions == {}

    service.settings = settings.model_copy(update={"wait_limit_s": 0.0})
    service._check_after.clear()
    await service.tick()
    run = await _get(sessionmaker, run_id)
    assert run.status == SimRunStatus.FAILED and "waited" in (run.status_reason or "")


async def test_a_paused_service_fails_the_run(
    settings: SimSettings,
    sessionmaker: async_sessionmaker[AsyncSession],
    fake_gateway: ModelGateway,
    fake_api: Any,
) -> None:
    """SM-3, SM-15: paused in Controls -> the run fails with the reason."""
    async with sessionmaker() as db:
        await rs.set(db, rs.SettingKey.SIM_PAUSED, True, actor="a@example.com")
        await db.commit()
    rs.clear_cache()
    service = _service(settings, sessionmaker, fake_gateway, fake_api(TOKEN))
    run_id = await _queue(sessionmaker)
    await service.tick()
    run = await _get(sessionmaker, run_id)
    assert run.status == SimRunStatus.FAILED and "paused" in (run.status_reason or "")


async def test_a_restart_fails_runs_that_were_active(
    settings: SimSettings,
    sessionmaker: async_sessionmaker[AsyncSession],
    fake_gateway: ModelGateway,
    fake_api: Any,
) -> None:
    """SM-4: after a restart, an active run cannot go on; it is failed with the reason."""
    run_id = await _queue(sessionmaker, status=SimRunStatus.INTERVIEWING)
    await _service(settings, sessionmaker, fake_gateway, fake_api(TOKEN)).recover()
    run = await _get(sessionmaker, run_id)
    assert run.status == SimRunStatus.FAILED and "restarted" in (run.status_reason or "")


# ---------------------------------------------------------------- files (SM-13, SM-14)

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


def _folder(name: str, days_ago: int, size_mb: float) -> retention.RunFolder:
    return retention.RunFolder(name, NOW - timedelta(days=days_ago), int(size_mb * 1024**2))


def test_retention_plan_by_age_then_size_never_kept_or_newest() -> None:
    """SM-14: older than 90 days first, then oldest until under the size limit."""
    folders = [
        _folder("a-old", 120, 1),
        _folder("b-old-kept", 100, 1),
        _folder("c", 30, 600),
        _folder("d-active", 20, 600),
        _folder("e", 10, 600),
        _folder("f-newest", 1, 600),
    ]
    out = retention.plan(folders, {"b-old-kept", "d-active"}, NOW, keep_days=90, keep_gb=1.5)
    assert out == [
        ("a-old", "older than 90 days"),
        ("c", "the runs folder was over 1.5 GB"),
        ("e", "the runs folder was over 1.5 GB"),
    ]
    assert retention.plan([_folder("only", 400, 99_999)], set(), NOW, 90, 0.001) == []


async def test_retention_and_delete_remove_folders_and_mark_rows(
    settings: SimSettings,
    sessionmaker: async_sessionmaker[AsyncSession],
    fake_gateway: ModelGateway,
    fake_api: Any,
) -> None:
    """SM-13: a deleted run's folder goes; SM-14: retention records itself on the row."""
    base = settings.out_dir
    old, kept, deleted, newest = (
        "20260101-000000-admin-0001", "20260102-000000-admin-0002",
        "20261001-000000-admin-0003", "20261017-000000-suite-0004",
    )  # fmt: skip
    for name in (old, kept, deleted, newest):
        (base / name).mkdir(parents=True)
        (base / name / "audio.ogg").write_bytes(b"x" * 10)
    done = SimRunStatus.DONE
    old_id = await _queue(sessionmaker, status=done, run_dir=old)
    await _queue(sessionmaker, status=done, run_dir=kept, keep=True)
    await _queue(sessionmaker, status=done, run_dir=deleted, deleted_at=datetime.now(UTC),
                 deleted_by="admin@example.com")  # fmt: skip
    service = _service(settings, sessionmaker, fake_gateway, fake_api(TOKEN))

    await service.sweep_deleted()
    assert not (base / deleted).exists()
    assert await service.apply_retention() == [old]
    assert sorted(p.name for p in base.iterdir()) == [kept, newest]
    run = await _get(sessionmaker, old_id)
    assert run.deleted_by == "retention" and run.deleted_at is not None
    assert run.delete_reason == "older than 90 days"


def test_delete_folder_refuses_paths_outside_the_runs_folder(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        retention.delete_folder(tmp_path, "../elsewhere")
    with pytest.raises(ValueError):
        retention.delete_folder(tmp_path, "")
