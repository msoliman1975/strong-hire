"""Arq jobs for gap analysis and the interviewer brief (GA-1 to GA-4)."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.config import get_settings
from strong_core.db.models import (
    Company,
    InterviewSession,
    JobTarget,
    Subscription,
    UsageEvent,
)
from strong_core.db.models import CompanyProfile as ProfileRow
from strong_core.db.models import GapAnalysis as GapRow
from strong_core.db.models import Resume as ResumeRow
from strong_core.gateway import ModelGateway
from strong_core.gateway.registry import fake_models_config
from strong_core.schemas import (
    Difficulty,
    GapAnalysis,
    GapStatus,
    InterviewerBrief,
    InterviewType,
    Mode,
    ProfileStatus,
    SubscriptionStatus,
)
from strong_worker.gap import jobs
from strong_worker.gap.jobs import CTX_KEY, GapContext, context_notes
from strong_worker.inputs.testing import RecordingBackend

ROOT = get_settings().repo_root
INPUTS = ROOT / "evals/fixtures/inputs"


def _json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


async def _setup(
    maker: async_sessionmaker[AsyncSession],
    account: tuple[uuid.UUID, uuid.UUID],
    *,
    company_slug: str | None = None,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    org_id, user_id = account
    async with maker() as db:
        company_id = None
        if company_slug:
            company = Company(slug=company_slug, name="Example Corp")
            db.add(company)
            await db.flush()
            company_id = company.id
            profile = _json(ROOT / "profiles/examples/example-corp.json")
            db.add(
                ProfileRow(
                    company_id=company.id,
                    version=2,
                    status=ProfileStatus.PUBLISHED,
                    profile_json=profile,
                    sources_json=profile["sources"],
                )
            )
        target = JobTarget(
            org_id=org_id,
            user_id=user_id,
            company_id=company_id,
            parsed_json=_json(INPUTS / "postings/swe-stripe-backend.json"),
            stage="Onsite or final loop",
            context_notes=json.dumps({"concerns": "System design depth"}),
        )
        resume = ResumeRow(
            org_id=org_id,
            user_id=user_id,
            parsed_json=_json(INPUTS / "resumes/backend-senior.json"),
        )
        db.add_all([target, resume])
        await db.flush()
        row = GapRow(
            org_id=org_id, job_target_id=target.id, resume_id=resume.id, status=GapStatus.RUNNING
        )
        db.add(row)
        await db.commit()
        return target.id, resume.id, row.id


def _ctx(maker: async_sessionmaker[AsyncSession], gateway: ModelGateway) -> dict[str, Any]:
    return {CTX_KEY: GapContext(sessionmaker=maker, gateway=gateway)}


async def test_gap_job_saves_a_ready_analysis(
    sessionmaker: async_sessionmaker[AsyncSession],
    account: tuple[uuid.UUID, uuid.UUID],
    gateway: ModelGateway,
) -> None:
    """GA-1 to GA-3: the job stores the score, the breakdown, the plan and the model version."""
    org_id, _ = account
    _, _, gap_id = await _setup(sessionmaker, account)
    result = await jobs.run_gap_analysis_job(_ctx(sessionmaker, gateway), str(gap_id), str(org_id))
    assert result["outcome"] == "ready"
    async with sessionmaker() as db:
        row = await db.get(GapRow, gap_id)
        assert row is not None
        assert row.status == GapStatus.READY and row.error is None
        assert row.breakdown_json is not None and row.session_plan_json
        analysis = GapAnalysis.model_validate(row.breakdown_json)
        assert row.match_score == analysis.match_score == result["match_score"]
        assert row.model_version and "planner/gap_analysis.v1" in row.model_version
        assert row.profile_version is None  # generic mode


async def test_gap_job_uses_the_published_profile(
    sessionmaker: async_sessionmaker[AsyncSession],
    account: tuple[uuid.UUID, uuid.UUID],
    gateway: ModelGateway,
) -> None:
    org_id, _ = account
    _, _, gap_id = await _setup(sessionmaker, account, company_slug="example-corp")
    await jobs.run_gap_analysis_job(_ctx(sessionmaker, gateway), str(gap_id), str(org_id))
    async with sessionmaker() as db:
        row = await db.get(GapRow, gap_id)
        assert row is not None and row.profile_version == 2


async def test_gap_job_sends_context_to_the_planner(
    sessionmaker: async_sessionmaker[AsyncSession],
    account: tuple[uuid.UUID, uuid.UUID],
    gateway: ModelGateway,
    backend: RecordingBackend,
) -> None:
    org_id, _ = account
    _, _, gap_id = await _setup(sessionmaker, account)
    await jobs.run_gap_analysis_job(_ctx(sessionmaker, gateway), str(gap_id), str(org_id))
    prompt = backend.calls[-1][-1].content
    assert "concerns: System design depth" in prompt
    assert "stage: Onsite or final loop" in prompt


async def test_gap_job_failure_is_saved_with_a_reason(
    sessionmaker: async_sessionmaker[AsyncSession],
    account: tuple[uuid.UUID, uuid.UUID],
    fake_fixtures: Path,
) -> None:
    org_id, _ = account
    _, _, gap_id = await _setup(sessionmaker, account)
    broken = ModelGateway(fake_models_config(), fake=RecordingBackend(fake_fixtures, fail_times=2))
    result = await jobs.run_gap_analysis_job(_ctx(sessionmaker, broken), str(gap_id), str(org_id))
    assert result == {"outcome": "failed", "reason": jobs.FAILED_REASON}
    async with sessionmaker() as db:
        row = await db.get(GapRow, gap_id)
        assert row is not None and row.status == GapStatus.FAILED
        assert row.error == jobs.FAILED_REASON and row.match_score is None


async def _hang(*_: object, **__: object) -> Any:
    await asyncio.Event().wait()


async def test_gap_job_timeout_marks_the_row_failed(
    sessionmaker: async_sessionmaker[AsyncSession],
    account: tuple[uuid.UUID, uuid.UUID],
    gateway: ModelGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GA-1: when the Arq job timeout cancels the job, the row is "failed", not "running"."""
    org_id, _ = account
    _, _, gap_id = await _setup(sessionmaker, account)
    monkeypatch.setattr(jobs, "run_gap_analysis", _hang)
    job = jobs.run_gap_analysis_job(_ctx(sessionmaker, gateway), str(gap_id), str(org_id))
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(job, timeout=0.2)  # what arq does at its job timeout
    async with sessionmaker() as db:
        row = await db.get(GapRow, gap_id)
        assert row is not None and row.status == GapStatus.FAILED
        assert row.error == jobs.FAILED_REASON


async def test_gap_job_unexpected_error_marks_the_row_failed(
    sessionmaker: async_sessionmaker[AsyncSession],
    account: tuple[uuid.UUID, uuid.UUID],
    gateway: ModelGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id, _ = account
    _, _, gap_id = await _setup(sessionmaker, account)

    async def boom(*_: object, **__: object) -> Any:
        raise RuntimeError("provider down")

    monkeypatch.setattr(jobs, "run_gap_analysis", boom)
    with pytest.raises(RuntimeError):
        await jobs.run_gap_analysis_job(_ctx(sessionmaker, gateway), str(gap_id), str(org_id))
    async with sessionmaker() as db:
        row = await db.get(GapRow, gap_id)
        assert row is not None and row.status == GapStatus.FAILED


async def test_gap_job_checks_the_org(
    sessionmaker: async_sessionmaker[AsyncSession],
    account: tuple[uuid.UUID, uuid.UUID],
    gateway: ModelGateway,
) -> None:
    _, _, gap_id = await _setup(sessionmaker, account)
    result = await jobs.run_gap_analysis_job(
        _ctx(sessionmaker, gateway), str(gap_id), str(uuid.uuid4())
    )
    assert result["outcome"] == "failed"


async def test_ga4_gap_job_does_not_use_plan_minutes(
    sessionmaker: async_sessionmaker[AsyncSession],
    account: tuple[uuid.UUID, uuid.UUID],
    gateway: ModelGateway,
) -> None:
    """GA-4: gap analysis is free. It works with no minutes left and does not change usage."""
    org_id, user_id = account
    async with sessionmaker() as db:
        db.add(
            Subscription(
                org_id=org_id,
                user_id=user_id,
                status=SubscriptionStatus.ACTIVE,
                minutes_cap=300,
                minutes_used=300,
            )
        )
        await db.commit()
    _, _, gap_id = await _setup(sessionmaker, account)
    result = await jobs.run_gap_analysis_job(_ctx(sessionmaker, gateway), str(gap_id), str(org_id))
    assert result["outcome"] == "ready"
    async with sessionmaker() as db:
        sub = await db.scalar(select(Subscription))
        assert sub is not None and sub.minutes_used == 300
        assert await db.scalar(select(func.count(UsageEvent.id))) == 0


async def test_brief_job_stores_the_brief_and_profile_version(
    sessionmaker: async_sessionmaker[AsyncSession],
    account: tuple[uuid.UUID, uuid.UUID],
    gateway: ModelGateway,
) -> None:
    org_id, _ = account
    target_id, _, gap_id = await _setup(sessionmaker, account, company_slug="example-corp")
    ctx = _ctx(sessionmaker, gateway)
    await jobs.run_gap_analysis_job(ctx, str(gap_id), str(org_id))
    async with sessionmaker() as db:
        session = InterviewSession(
            org_id=org_id,
            job_target_id=target_id,
            type=InterviewType.HIRING_MANAGER,
            difficulty=Difficulty.TOUGH,
            mode=Mode.COACH,
            duration_min=45,
        )
        db.add(session)
        await db.commit()
        session_id = session.id
    result = await jobs.build_interviewer_brief(ctx, str(session_id), str(org_id))
    assert result["outcome"] == "ready"
    assert result["tokens"] <= 1500
    async with sessionmaker() as db:
        stored = await db.get(InterviewSession, session_id)
        assert stored is not None and stored.brief_json is not None
        assert stored.profile_version == 2
        brief = InterviewerBrief.model_validate(stored.brief_json)
        assert brief.profile_version == 2 and brief.curveball and brief.coach_help
        assert brief.session.duration_min == 45
        assert brief.probe_areas  # from the gap analysis


async def test_brief_job_keeps_a_10_minute_session_as_a_mini(
    sessionmaker: async_sessionmaker[AsyncSession],
    account: tuple[uuid.UUID, uuid.UUID],
    gateway: ModelGateway,
) -> None:
    """A 10-minute session gets a mini brief; before, any length other than 45 became 30."""
    org_id, _ = account
    target_id, _, gap_id = await _setup(sessionmaker, account)
    ctx = _ctx(sessionmaker, gateway)
    await jobs.run_gap_analysis_job(ctx, str(gap_id), str(org_id))
    async with sessionmaker() as db:
        session = InterviewSession(
            org_id=org_id,
            job_target_id=target_id,
            type=InterviewType.CASE,
            difficulty=Difficulty.TOUGH,
            mode=Mode.REALISTIC,
            duration_min=10,
        )
        db.add(session)
        await db.commit()
        session_id = session.id
    result = await jobs.build_interviewer_brief(ctx, str(session_id), str(org_id))
    assert result["outcome"] == "ready"
    async with sessionmaker() as db:
        stored = await db.get(InterviewSession, session_id)
        assert stored is not None and stored.brief_json is not None
        brief = InterviewerBrief.model_validate(stored.brief_json)
        assert brief.session.duration_min == 10
        assert len(brief.questions) == 3
        assert brief.curveball is None and brief.max_probes_per_question == 1


def test_context_notes_are_plain_lines() -> None:
    target = JobTarget(stage="Phone screen", context_notes=json.dumps({"interviewer_name": "Ana"}))
    assert context_notes(target) == "stage: Phone screen\ninterviewer name: Ana"
    assert context_notes(JobTarget()) is None
