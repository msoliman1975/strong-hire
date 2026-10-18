"""OC-5: paused job kinds wait in the queue (arq Retry, 60 s) instead of running."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from arq import Retry
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core import runtime_settings as rs
from strong_core.db.models import GapAnalysis as GapRow
from strong_core.gateway import ModelGateway
from strong_core.schemas import GapStatus
from strong_worker import pause
from strong_worker.gap import jobs as gap_jobs
from strong_worker.main import WorkerSettings
from strong_worker.scoring import jobs as scoring_jobs

from .test_gap_jobs import _setup

Maker = async_sessionmaker[AsyncSession]


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    rs.clear_cache()
    yield
    rs.clear_cache()


async def _pause(maker: Maker, *kinds: str) -> None:
    async with maker() as db:
        await rs.set(db, rs.SettingKey.JOBS_PAUSED, list(kinds), actor="ops@example.com")
        await db.commit()


def _ctx(maker: Maker, gateway: ModelGateway, job_try: int = 1) -> dict[str, Any]:
    return {
        gap_jobs.CTX_KEY: gap_jobs.GapContext(sessionmaker=maker, gateway=gateway),
        scoring_jobs.CTX_KEY: scoring_jobs.ScoringContext(sessionmaker=maker, gateway=gateway),
        "job_try": job_try,
        "job_id": "test-job",
    }


async def test_oc5_paused_gap_analysis_waits_and_the_row_stays_running(
    sessionmaker: Maker, account: tuple[uuid.UUID, uuid.UUID], gateway: ModelGateway
) -> None:
    org_id, _ = account
    _, _, gap_id = await _setup(sessionmaker, account)
    await _pause(sessionmaker, "gap_analysis")
    with pytest.raises(Retry) as caught:
        await gap_jobs.run_gap_analysis_job(_ctx(sessionmaker, gateway), str(gap_id), str(org_id))
    assert caught.value.defer_score == pause.PAUSED_DEFER_S * 1000
    async with sessionmaker() as db:
        row = await db.get(GapRow, gap_id)
        assert row is not None and row.status == GapStatus.RUNNING  # not marked failed
    await _pause(sessionmaker)  # unpaused: the next try runs
    result = await gap_jobs.run_gap_analysis_job(
        _ctx(sessionmaker, gateway, job_try=2), str(gap_id), str(org_id)
    )
    assert result["outcome"] == "ready"


async def test_oc5_paused_scoring_waits_and_other_kinds_run(
    sessionmaker: Maker, account: tuple[uuid.UUID, uuid.UUID], gateway: ModelGateway
) -> None:
    org_id, _ = account
    missing = str(uuid.uuid4())
    await _pause(sessionmaker, "scoring")
    with pytest.raises(Retry):
        await scoring_jobs.score_session(_ctx(sessionmaker, gateway), missing, str(org_id))
    _, _, gap_id = await _setup(sessionmaker, account)
    result = await gap_jobs.run_gap_analysis_job(
        _ctx(sessionmaker, gateway), str(gap_id), str(org_id)
    )
    assert result["outcome"] == "ready"  # gap analysis is not paused
    await _pause(sessionmaker)
    result = await scoring_jobs.score_session(_ctx(sessionmaker, gateway), missing, str(org_id))
    assert result == {"outcome": "failed", "reason": "session not found"}


async def test_oc5_a_job_on_its_last_try_runs_anyway(
    sessionmaker: Maker, gateway: ModelGateway
) -> None:
    await _pause(sessionmaker, "scoring")
    ctx = _ctx(sessionmaker, gateway, job_try=pause.PAUSED_MAX_TRIES)
    await pause.wait_if_paused(ctx, sessionmaker, rs.JobKind.SCORING)  # no Retry


async def test_oc5_an_unreadable_setting_does_not_hold_jobs(gateway: ModelGateway) -> None:
    class Broken:
        def __call__(self) -> Any:
            raise RuntimeError("no database")

    ctx = _ctx(Broken(), gateway)  # type: ignore[arg-type]
    await pause.wait_if_paused(ctx, Broken(), rs.JobKind.GAP_ANALYSIS)  # type: ignore[arg-type]


def test_oc5_pausable_jobs_may_retry_for_a_day() -> None:
    tries = {f.name: f.max_tries for f in WorkerSettings.functions if hasattr(f, "max_tries")}
    assert tries["run_gap_analysis_job"] == pause.PAUSED_MAX_TRIES
    assert tries["score_session"] == pause.PAUSED_MAX_TRIES
