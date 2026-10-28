"""Practice readiness per skill for one job and CV pair (RD-1, RD-3). Rules in code, no model.

    GET /plan/{job_target_id}/{resume_id}/readiness    the plan page's per-skill view
    GET /readiness/{job_target_id}                     the Home card's badge: the job's latest pair

Which sessions count. A session counts toward readiness only when all of these hold:
- it is an interview session of this job with this CV (the pair);
- its mode is Realistic (PR-1). Coach mode never counts;
- it is a full session, not the 10-minute mini interview (minis have no progress snapshots);
- its model profile is a real one: sessions on `fake`, `tiny` or `local` are development data
  (PL-6) and never count. A session with no recorded profile does not count either.
Coach sessions (CO-2) and takes (CO-7) live in their own tables and are never read here.

The formula. For each tested skill, take that skill's progress snapshots (one per counted
session, a 1 to 4 average) and sort them newest first. The newest gets weight 1, the one before
0.5 ** (1 / HALF_LIFE) of that, and so on: each step back halves the weight every HALF_LIFE
sessions. The weighted mean m (1 to 4) becomes the score round((m - 1) / 3 * 100), 0 to 100.
Only the newest MAX_SESSIONS snapshots are used. Fewer than MIN_SESSIONS counted sessions for a
skill gives `not_enough_data` and no score. A score of BAR_SCORE or more (a 3 of 4, the rubric's
bar) is "at the bar".

Tested skills are the competencies of the types in the company's loop for this role family, in
loop order. With no loop (generic mode), they are the competencies of the four standard types.

Readiness is a practice estimate from AI-scored rehearsals, not a prediction of the hiring
decision (RD-3). `Readiness.kind` is always `practice_estimate`, and every screen that shows it
shows that notice.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.inputs.deps import Db, Me
from strong_api.inputs.router import _owned_job_target, _owned_resume
from strong_api.plan import service
from strong_api.plan.schemas import TypeWeights
from strong_core.config import ModelProfile
from strong_core.db.models import InterviewSession, JobTarget
from strong_core.db.models import ProgressSnapshot as SnapshotRow
from strong_core.profiles import resolve_profile
from strong_core.schemas import (
    MINI_DURATION_MIN,
    Competency,
    Mode,
    Readiness,
    ReadinessStatus,
    SkillReadiness,
)

router = APIRouter(tags=["interview plan"])

MIN_SESSIONS = 2
MAX_SESSIONS = 8
HALF_LIFE = 2.0
BAR_SCORE = 67  # (3 - 1) / 3 * 100, rounded
# PL-6: sessions on these profiles are development data.
DEV_PROFILES = frozenset({ModelProfile.FAKE, ModelProfile.TINY, ModelProfile.LOCAL})


def counts_for_readiness(mode: Mode, duration_min: int, model_profile: str | None) -> bool:
    """RD-1: Realistic, full length and on a real model profile (rules in the docstring)."""
    return (
        mode == Mode.REALISTIC
        and duration_min != MINI_DURATION_MIN
        and model_profile is not None
        and model_profile not in DEV_PROFILES
    )


@dataclass(frozen=True)
class SkillPoint:
    """One counted session's score for one skill (1 to 4)."""

    competency: Competency
    score: float
    at: datetime


def to_score(mean: float) -> int:
    """A 1 to 4 rubric mean as 0 to 100."""
    return max(0, min(100, round((mean - 1) / 3 * 100)))


def weighted_mean(scores_newest_first: Sequence[float]) -> float:
    weights: list[float] = [0.5 ** (i / HALF_LIFE) for i in range(len(scores_newest_first))]
    total = sum(w * s for w, s in zip(weights, scores_newest_first, strict=True))
    return float(total / sum(weights))


def skill_readiness(competency: Competency, points: Iterable[SkillPoint]) -> SkillReadiness:
    newest = sorted(points, key=lambda p: p.at, reverse=True)[:MAX_SESSIONS]
    if len(newest) < MIN_SESSIONS:
        return SkillReadiness(
            competency=competency,
            status=ReadinessStatus.NOT_ENOUGH_DATA,
            score=None,
            sessions_counted=len(newest),
        )
    return SkillReadiness(
        competency=competency,
        status=ReadinessStatus.SCORED,
        score=to_score(weighted_mean([p.score for p in newest])),
        sessions_counted=len(newest),
    )


def compute_readiness(
    job_target_id: uuid.UUID,
    skills: Sequence[Competency],
    points: Iterable[SkillPoint],
    as_of: date,
) -> Readiness:
    """RD-1: one entry per tested skill, in the given order. Points of other skills are ignored."""
    by: dict[Competency, list[SkillPoint]] = defaultdict(list)
    for p in points:
        by[p.competency].append(p)
    return Readiness(
        job_target_id=job_target_id,
        as_of=as_of,
        skills=[skill_readiness(c, by.get(c, [])) for c in dict.fromkeys(skills)],
    )


def tested_skills(tested: Sequence[TypeWeights]) -> list[Competency]:
    """The loop's competencies in loop order; all standard types' when there is no loop."""
    chosen = [t for t in tested if t.in_loop] or list(tested)
    out: list[Competency] = []
    for t in chosen:
        for c in t.competencies:
            if c.competency not in out:
                out.append(c.competency)
    return out


async def pair_points(
    db: AsyncSession, job_target_id: uuid.UUID, resume_id: uuid.UUID
) -> list[SkillPoint]:
    """The snapshots of the pair's sessions that count (RD-1 rules)."""
    rows = await db.execute(
        select(
            SnapshotRow.competency,
            SnapshotRow.score,
            SnapshotRow.at,
            InterviewSession.mode,
            InterviewSession.duration_min,
            InterviewSession.model_profile,
        )
        .join(InterviewSession, InterviewSession.id == SnapshotRow.session_id)
        .where(
            SnapshotRow.job_target_id == job_target_id,
            InterviewSession.job_target_id == job_target_id,
            InterviewSession.resume_id == resume_id,
        )
    )
    return [
        SkillPoint(competency=c, score=float(score), at=at)
        for c, score, at, mode, duration, profile in rows
        if counts_for_readiness(mode, duration, profile)
    ]


async def readiness_for(db: AsyncSession, target: JobTarget, resume_id: uuid.UUID) -> Readiness:
    profile = await resolve_profile(db, target.company_id)
    skills = tested_skills(service.tested(profile, target))
    points = await pair_points(db, target.id, resume_id)
    return compute_readiness(target.id, skills, points, service.today())


async def latest_pair_resume(db: AsyncSession, job_target_id: uuid.UUID) -> uuid.UUID | None:
    """The CV of the job's newest session that has one."""
    return await db.scalar(
        select(InterviewSession.resume_id)
        .where(
            InterviewSession.job_target_id == job_target_id,
            InterviewSession.resume_id.is_not(None),
        )
        .order_by(InterviewSession.created_at.desc())
        .limit(1)
    )


@router.get(
    "/plan/{job_target_id}/{resume_id}/readiness",
    responses={404: {"description": "The job target or the resume does not exist."}},
)
async def get_readiness(
    job_target_id: uuid.UUID, resume_id: uuid.UUID, db: Db, me: Me
) -> Readiness:
    """RD-1: practice readiness per tested skill for this pair. RD-3: a practice estimate."""
    target = await _owned_job_target(db, me, job_target_id)
    resume = await _owned_resume(db, me, resume_id)
    return await readiness_for(db, target, resume.id)


@router.get(
    "/readiness/{job_target_id}",
    responses={404: {"description": "The job target does not exist."}},
)
async def get_job_readiness(job_target_id: uuid.UUID, db: Db, me: Me) -> Readiness:
    """RD-1 for the Home card: the pair of the job's newest session. No session yet: every
    tested skill is not_enough_data."""
    target = await _owned_job_target(db, me, job_target_id)
    resume_id = await latest_pair_resume(db, target.id)
    if resume_id is None:
        profile = await resolve_profile(db, target.company_id)
        skills = tested_skills(service.tested(profile, target))
        return compute_readiness(target.id, skills, [], service.today())
    return await readiness_for(db, target, resume_id)
