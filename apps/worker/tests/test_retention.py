"""Trace retention (R2): a daily cron job deletes interviewer traces older than 90 days and keeps
the transcript."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from arq.cron import CronJob
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import (
    TRACE_RETENTION_DAYS,
    InterviewerTrace,
    InterviewSession,
    JobTarget,
    Turn,
)
from strong_core.schemas import Difficulty, InterviewType, Mode, Phase, Speaker
from strong_worker import retention
from strong_worker.main import WorkerSettings

Maker = async_sessionmaker[AsyncSession]


async def _fill(maker: Maker, org_id: uuid.UUID, user_id: uuid.UUID, now: datetime) -> None:
    async with maker() as db:
        job = JobTarget(org_id=org_id, user_id=user_id, raw_text="Engineer")
        db.add(job)
        await db.flush()
        session = InterviewSession(
            org_id=org_id,
            job_target_id=job.id,
            type=InterviewType.BEHAVIORAL,
            difficulty=Difficulty.REALISTIC,
            mode=Mode.REALISTIC,
            duration_min=30,
        )
        db.add(session)
        await db.flush()
        for seq, age_days in enumerate((120, 91, 89, 1), start=1):
            db.add(
                InterviewerTrace(
                    org_id=org_id,
                    session_id=session.id,
                    seq=seq,
                    turn_index=seq,
                    call="say",
                    move="ask",
                    phase=Phase.CORE,
                    elapsed_ms=0,
                    input_tokens=0,
                    output_tokens=0,
                    created_at=now - timedelta(days=age_days),
                )
            )
        db.add(
            Turn(
                org_id=org_id,
                session_id=session.id,
                speaker=Speaker.INTERVIEWER,
                phase=Phase.CORE,
                text="Tell me about a project.",
                start_ms=0,
                end_ms=1000,
            )
        )
        await db.commit()


async def test_r2_old_traces_are_deleted_and_turns_stay(
    sessionmaker: Maker, account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    now = datetime.now(UTC)
    await _fill(sessionmaker, *account, now)
    deleted = await retention.delete_old_traces(sessionmaker, now=now)
    assert deleted == 2
    async with sessionmaker() as db:
        left = list(await db.scalars(select(InterviewerTrace.seq).order_by(InterviewerTrace.seq)))
        turns = await db.scalar(select(func.count()).select_from(Turn))
    assert left == [3, 4]  # 89 and 1 days old
    assert turns == 1
    assert TRACE_RETENTION_DAYS == 90


async def test_r2_retention_runs_as_a_daily_cron_job(
    sessionmaker: Maker, account: tuple[uuid.UUID, uuid.UUID]
) -> None:
    jobs = [j for j in WorkerSettings.cron_jobs if isinstance(j, CronJob)]
    assert [j.coroutine for j in jobs] == [retention.trace_retention]
    job = jobs[0]
    assert job.hour == retention.RUN_AT_HOUR_UTC and job.minute == retention.RUN_AT_MINUTE
    await _fill(sessionmaker, *account, datetime.now(UTC))
    result = await retention.trace_retention({retention.CTX_KEY: sessionmaker})
    assert result == {"deleted": 2}
