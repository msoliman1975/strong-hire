"""Arq jobs for gap analysis (GA-1 to GA-4) and the interviewer brief.

The API creates a gap_analyses row with status "running" and enqueues `run_gap_analysis`. The
job fills in the result and sets status "ready", or "failed" with a plain reason. The API reads
the row; it does not need the Arq job result. If the job stops in any other way (the Arq job
timeout cancels it, or an unexpected error), the row is still marked "failed", so the page never
waits forever.

`build_interviewer_brief` builds the brief for a session row and stores it in brief_json. The
sessions workstream enqueues it when a session is created. When the brief fails for good, the
session is marked "failed" before it started, so nobody waits for it forever.

Neither job records usage minutes: gap analysis is free (GA-4).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from arq import Retry
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db import get_sessionmaker
from strong_core.db.models import GapAnalysis as GapRow
from strong_core.db.models import InterviewSession, JobTarget
from strong_core.db.models import Resume as ResumeRow
from strong_core.gateway import ModelGateway, get_gateway
from strong_core.profiles import resolve_profile, use_profile_for_session
from strong_core.schemas import (
    GapAnalysis,
    GapStatus,
    JobPosting,
    Level,
    Resume,
    SessionConfig,
    SessionStatus,
    session_duration,
)
from strong_core.sim import gateway_for_org
from strong_worker.gap.analysis import GapAnalysisError, run_gap_analysis
from strong_worker.gap.brief import BriefError, build_brief

log = logging.getLogger(__name__)

CTX_KEY = "gap"
RESULT_TTL_S = 24 * 3600
FAILED_REASON = "The analysis did not finish. Try again in a minute."
# The brief job: tries in all (Arq max_tries), and the wait before the second try. The planner
# already makes 2 calls per try, so a short provider error gets 4 calls over about 20 seconds.
BRIEF_MAX_TRIES = 2
BRIEF_RETRY_DEFER_S = 15
BRIEF_FAILED_REASON = "The interview plan did not finish."


@dataclass
class GapContext:
    sessionmaker: async_sessionmaker[AsyncSession]
    gateway: ModelGateway


async def startup(ctx: dict[str, Any]) -> None:
    ctx[CTX_KEY] = GapContext(sessionmaker=get_sessionmaker(), gateway=get_gateway())


def _gap(ctx: dict[str, Any]) -> GapContext:
    value = ctx[CTX_KEY]
    assert isinstance(value, GapContext)
    return value


def context_notes(target: JobTarget) -> str | None:
    """The IN-4 context as plain lines for the planner prompt."""
    lines = []
    if target.stage:
        lines.append(f"stage: {target.stage}")
    if target.context_notes:
        try:
            data = json.loads(target.context_notes)
        except ValueError:
            data = {"notes": target.context_notes}
        if isinstance(data, dict):
            lines += [f"{k.replace('_', ' ')}: {v}" for k, v in data.items() if v]
    return "\n".join(lines) or None


async def run_gap_analysis_job(
    ctx: dict[str, Any], gap_analysis_id: str, org_id: str
) -> dict[str, Any]:
    """Compute one gap analysis row (GA-1 to GA-3)."""
    gap = _gap(ctx)
    try:
        return await _run_gap_analysis(gap, gap_analysis_id, org_id)
    except BaseException:
        # The Arq job timeout cancels the task (asyncio.CancelledError), or something failed that
        # run_gap_analysis does not turn into GapAnalysisError. Without this, the row would stay
        # "running" and the page would wait forever. Shielded, so the cancel cannot stop it.
        await asyncio.shield(_mark_failed_if_running(gap, gap_analysis_id, org_id))
        raise


async def _mark_failed_if_running(gap: GapContext, gap_analysis_id: str, org_id: str) -> None:
    try:
        async with gap.sessionmaker() as db:
            await db.execute(
                update(GapRow)
                .where(
                    GapRow.id == uuid.UUID(gap_analysis_id),
                    GapRow.org_id == uuid.UUID(org_id),
                    GapRow.status == GapStatus.RUNNING,
                )
                .values(status=GapStatus.FAILED, error=FAILED_REASON, updated_at=datetime.now(UTC))
            )
            await db.commit()
    except Exception:
        log.exception("could not mark gap analysis %s as failed", gap_analysis_id)


async def _run_gap_analysis(gap: GapContext, gap_analysis_id: str, org_id: str) -> dict[str, Any]:
    async with gap.sessionmaker() as db:
        row = await db.scalar(
            select(GapRow).where(
                GapRow.id == uuid.UUID(gap_analysis_id), GapRow.org_id == uuid.UUID(org_id)
            )
        )
        if row is None:
            return {"outcome": "failed", "reason": "gap analysis not found"}
        target = await db.get(JobTarget, row.job_target_id)
        resume_row = await db.get(ResumeRow, row.resume_id)
        problem = None
        if target is None or target.parsed_json is None:
            problem = "The job posting is not ready yet."
        elif resume_row is None or resume_row.parsed_json is None:
            problem = "The resume is not ready yet."
        if problem is not None:
            return await _fail(db, row, problem)
        assert target is not None and resume_row is not None
        posting = JobPosting.model_validate(target.parsed_json)
        resume = Resume.model_validate(resume_row.parsed_json)
        profile = await resolve_profile(db, target.company_id)
        try:
            gateway = await gateway_for_org(db, row.org_id, gap.gateway)  # sim budget (P13)
            result = await run_gap_analysis(
                gateway, posting, resume, profile, context_notes=context_notes(target)
            )
        except GapAnalysisError as exc:
            log.warning("gap analysis %s failed: %s", row.id, exc)
            return await _fail(db, row, FAILED_REASON)

        analysis = result.analysis
        row.status = GapStatus.READY
        row.error = None
        row.match_score = analysis.match_score
        row.breakdown_json = analysis.model_dump(mode="json")
        row.session_plan_json = [p.model_dump(mode="json") for p in analysis.session_plan]
        row.model_version = result.model_version
        row.profile_version = profile.version
        row.updated_at = datetime.now(UTC)
        await db.commit()
        return {
            "outcome": "ready",
            "match_score": analysis.match_score,
            "flags": result.flags,
            "model": result.model_version,
            "attempts": result.attempts,
        }


async def _fail(db: AsyncSession, row: GapRow, reason: str) -> dict[str, Any]:
    row.status = GapStatus.FAILED
    row.error = reason
    row.updated_at = datetime.now(UTC)
    await db.commit()
    return {"outcome": "failed", "reason": reason}


async def latest_ready_gap(
    db: AsyncSession, job_target_id: uuid.UUID, resume_id: uuid.UUID | None = None
) -> GapRow | None:
    """The job's latest ready gap analysis; with resume_id, the latest one for that CV (PR-3)."""
    query = select(GapRow).where(
        GapRow.job_target_id == job_target_id, GapRow.status == GapStatus.READY
    )
    if resume_id is not None:
        query = query.where(GapRow.resume_id == resume_id)
    return await db.scalar(query.order_by(GapRow.created_at.desc(), GapRow.id.desc()).limit(1))


async def build_interviewer_brief(
    ctx: dict[str, Any], session_id: str, org_id: str
) -> dict[str, Any]:
    """Build the InterviewerBrief for a session and store it in sessions.brief_json.

    Uses the job's latest ready gap analysis and its resume. Records the profile version on the
    session (generic mode stores NULL).

    If the planner fails (for example the model provider returns an error), Arq runs the job
    once more after BRIEF_RETRY_DEFER_S. When it fails for good, or stops in any other way, the
    session is marked "failed" before it started, so the web app and the AI candidate stop
    waiting. Such a session is never billed and does not use a free interview.
    """
    gap = _gap(ctx)
    try:
        return await _build_interviewer_brief(gap, session_id, org_id, ctx.get("job_try", 1))
    except Retry:
        raise
    except BaseException:
        # The Arq job timeout cancels the task, or something failed that build_brief does not
        # turn into BriefError. Shielded, so the cancel cannot stop it.
        log.exception("brief job for session %s stopped", session_id)
        await asyncio.shield(_mark_session_failed(gap, session_id, org_id))
        raise


async def _mark_session_failed(gap: GapContext, session_id: str, org_id: str) -> None:
    """Mark a session that never started and has no brief as failed. Never raises."""
    try:
        async with gap.sessionmaker() as db:
            await db.execute(
                update(InterviewSession)
                .where(
                    InterviewSession.id == uuid.UUID(session_id),
                    InterviewSession.org_id == uuid.UUID(org_id),
                    InterviewSession.status == SessionStatus.CREATED,
                    InterviewSession.started_at.is_(None),
                    InterviewSession.brief_json.is_(None),
                )
                .values(status=SessionStatus.FAILED)
            )
            await db.commit()
    except Exception:
        log.exception("could not mark session %s as failed", session_id)


async def _build_interviewer_brief(
    gap: GapContext, session_id: str, org_id: str, job_try: int
) -> dict[str, Any]:
    async with gap.sessionmaker() as db:
        session = await db.scalar(
            select(InterviewSession).where(
                InterviewSession.id == uuid.UUID(session_id),
                InterviewSession.org_id == uuid.UUID(org_id),
            )
        )
        if session is None:
            return {"outcome": "failed", "reason": "session not found"}
        if session.status != SessionStatus.CREATED or session.brief_json is not None:
            # Ended, failed or already built (for example a retry after a worker restart).
            return {"outcome": "skipped", "reason": f"session is {session.status.value}"}
        target = await db.get(JobTarget, session.job_target_id)
        if target is None or target.parsed_json is None:
            session.status = SessionStatus.FAILED
            await db.commit()
            return {"outcome": "failed", "reason": "The job posting is not ready yet."}
        posting = JobPosting.model_validate(target.parsed_json)
        gap_row = await latest_ready_gap(db, target.id, session.resume_id)
        analysis = None
        resume = None
        if gap_row is not None and gap_row.breakdown_json is not None:
            analysis = GapAnalysis.model_validate(gap_row.breakdown_json)
            resume_row = await db.get(ResumeRow, gap_row.resume_id)
            if resume_row is not None and resume_row.parsed_json is not None:
                resume = Resume.model_validate(resume_row.parsed_json)
        profile = await use_profile_for_session(db, session)
        config = SessionConfig(
            interview_type=session.type,
            difficulty=session.difficulty,
            mode=session.mode,
            duration_min=session_duration(session.duration_min),
            level=target.level or posting.level or Level.MID,
        )
        try:
            gateway = await gateway_for_org(db, session.org_id, gap.gateway)
            built = await build_brief(gateway, config, posting, resume, profile, gap=analysis)
        except BriefError as exc:
            if job_try < BRIEF_MAX_TRIES:
                log.warning(
                    "brief for session %s failed on try %d; retrying in %ds: %s",
                    session.id,
                    job_try,
                    BRIEF_RETRY_DEFER_S,
                    exc,
                )
                raise Retry(defer=BRIEF_RETRY_DEFER_S) from exc
            log.warning("brief for session %s failed for good: %s", session.id, exc)
            session.status = SessionStatus.FAILED
            await db.commit()
            return {"outcome": "failed", "reason": BRIEF_FAILED_REASON, "error": str(exc)[:500]}
        session.brief_json = built.brief.model_dump(mode="json")
        await db.commit()
        return {
            "outcome": "ready",
            "tokens": built.tokens,
            "flags": built.flags,
            "model": built.model_version,
        }


FUNCTIONS = (run_gap_analysis_job, build_interviewer_brief)
