"""Build the plan page's view from what other modules already compute (PP-1, PP-2, PP-4).

Nothing here is new analysis: the gap analysis (GA-1 to GA-3), the reports (PR-3) and the next
session (PR-2) come from their own modules. This module adds the profile weights per type, the
days left and the setup defaults.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.plan.schemas import CompetencyWeight, PlanSetupDefaults, TypeWeights
from strong_core.db.models import GapAnalysis as GapRow
from strong_core.db.models import JobTarget
from strong_core.profiles import ResolvedProfile
from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    STANDARD_INTERVIEW_TYPES,
    Difficulty,
    GapAnalysis,
    InterviewType,
    JobPosting,
    Level,
    Mode,
    PlannedSession,
    Tone,
)

DEFAULT_DURATION_MIN = 30


def today() -> date:
    return datetime.now(UTC).date()


def days_left(interview_date: date | None, now: date | None = None) -> int | None:
    """PP-2: days to the interview. 0 is today; negative once it has passed."""
    if interview_date is None:
        return None
    return (interview_date - (now or today())).days


async def latest_pair_gap(
    db: AsyncSession, job_target_id: uuid.UUID, resume_id: uuid.UUID
) -> GapRow | None:
    """The newest gap analysis run of this job with this CV, in any status."""
    return await db.scalar(
        select(GapRow)
        .where(GapRow.job_target_id == job_target_id, GapRow.resume_id == resume_id)
        .order_by(GapRow.created_at.desc(), GapRow.updated_at.desc().nulls_last())
        .limit(1)
    )


def loop_types(profile: ResolvedProfile, target: JobTarget) -> list[InterviewType]:
    """The interview types of the company's loop for the job's role family, in loop order."""
    if profile.profile is None or target.parsed_json is None:
        return []
    family = JobPosting.model_validate(target.parsed_json).role_family
    found: list[InterviewType] = []
    for loop in profile.profile.loop_structure:
        if loop.role_family != family:
            continue
        for round_ in loop.rounds:
            kind = round_.interview_type
            if kind is not None and kind not in found:
                found.append(kind)
    return found


def tested(profile: ResolvedProfile, target: JobTarget) -> list[TypeWeights]:
    """What they'll test: each type's competencies with the profile's weights.

    The loop's types for this role family come first; the other standard types follow so the
    page can still show them. Generic mode has no loop and equal weights.
    """
    in_loop = loop_types(profile, target)
    order = in_loop + [t for t in STANDARD_INTERVIEW_TYPES if t not in in_loop]
    out: list[TypeWeights] = []
    for kind in order:
        comps = COMPETENCIES_BY_TYPE.get(kind, ())
        weights = {c: profile.scoring_weights.get(c, 1.0) for c in comps}
        total = sum(weights.values()) or 1.0
        rows = [
            CompetencyWeight(competency=c, weight=w, share=round(w / total, 3))
            for c, w in weights.items()
        ]
        rows.sort(key=lambda r: (-r.weight, comps.index(r.competency)))
        out.append(TypeWeights(interview_type=kind, in_loop=kind in in_loop, competencies=rows))
    return out


def setup_defaults(
    *,
    generic: bool,
    analysis: GapAnalysis | None,
    next_session: PlannedSession | None,
    level: Level | None,
) -> PlanSetupDefaults:
    """PP-4: start from PR-2's advice, else the first planned session (GA-3), else Behavioral."""
    planned = next_session
    if planned is None and analysis is not None and analysis.session_plan:
        planned = min(analysis.session_plan, key=lambda p: p.priority)
    return PlanSetupDefaults(
        interview_type=planned.interview_type if planned else InterviewType.BEHAVIORAL,
        difficulty=planned.difficulty if planned else Difficulty.REALISTIC,
        # Coach first, as on the v1 setup page: the controls help a new candidate.
        mode=Mode.COACH,
        duration_min=DEFAULT_DURATION_MIN,
        level=level,
        tone=Tone.NEUTRAL if generic else Tone.AS_COMPANY,  # TN-3
    )
