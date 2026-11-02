"""Target roles, their interviews and readiness per interview (TG-3, RH-1, RH-2).

    GET    /roles                                    every role with its interviews' readiness
    GET    /roles/{job_target_id}/suggested-interviews   TG-3: the company's usual rounds
    GET    /roles/{job_target_id}/interviews         RH-1: the role's interviews
    POST   /roles/{job_target_id}/interviews         RH-1: keep the chosen types as interviews
    DELETE /interviews/{interview_id}                 RH-1: archive one (its takes stay)
    GET    /interviews/{interview_id}                 RH-2: interview, role, readiness and takes
    GET    /rehearsals                                every interview and the recommended next take

An interview is role x resume x type (`target_interviews`). Its takes are the sessions with the
same job target, resume and type, so sessions from before interviews existed map to theirs.

Readiness (ux-spec section 9), rules in code, no model. Only Realistic takes count, and only
scored ones on a real model profile (PL-6, as RD-1: fake, tiny and local sessions are development
data). For each competency of the interview type, take its most recent rubric score from the last
three counted takes; readiness = round((mean - 1) / 3 * 100) over the competencies scored so far.
No counted take: no score. The change is the score now minus the score before the newest counted
take. Readiness is a practice estimate (RD-3), never a prediction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.inputs.deps import Db, Me
from strong_api.inputs.router import _owned_job_target, job_target_name
from strong_api.plan import service
from strong_api.plan.readiness import DEV_PROFILES
from strong_api.scoring.router import answers_at_bar
from strong_core.db.models import InterviewSession, JobTarget, TargetInterview
from strong_core.db.models import Resume as ResumeRow
from strong_core.db.models import Scorecard as ScorecardRow
from strong_core.profiles import ResolvedProfile, resolve_profile
from strong_core.role_families import family_info
from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    READINESS_GOAL,
    Competency,
    CompetencyReadiness,
    CustomSessionSpec,
    HireSignal,
    InterviewReadiness,
    InterviewType,
    JobPosting,
    Mode,
    RoleFamily,
    Scorecard,
    SessionStatus,
)

router = APIRouter(tags=["target roles and interviews"])

TAKES_COUNTED = 3
"""RH-2: readiness reads the last three Realistic takes."""


def _family(target: JobTarget, family: RoleFamily | None = None) -> RoleFamily:
    """The job's role family: `family` when the caller previews an edit (RF-10), else the stored
    posting's, else OTHER until the posting is parsed."""
    if family is not None:
        return family
    posting = _posting(target)
    return posting.role_family if posting is not None else RoleFamily.OTHER


DESCRIPTIONS: dict[InterviewType, str] = {
    InterviewType.BEHAVIORAL: "Past situations: ownership, conflict, impact and what you learned.",
    InterviewType.HIRING_MANAGER: "Your experience in depth: judgment, scope and fit for the team.",
    InterviewType.TECHNICAL_QA: "Talk through technical topics: depth, accuracy and trade-offs.",
    InterviewType.CASE: "Work a business or product problem out loud, with a recommendation.",
    InterviewType.RECRUITER_SCREEN: "Motivation, background and logistics, in a short first call.",
    InterviewType.CUSTOM: "Your own mix of question types and questions.",
}


# --- contracts -----------------------------------------------------------------------------


class ActingAs(BaseModel):
    """SV-6: "Strova is acting as {title} at {company}" ("a {title}" in generic mode)."""

    title: str
    company: str | None
    text: str = Field(description="The full line the live room shows.")


class SuggestedInterview(BaseModel):
    interview_type: InterviewType
    description: str
    usual: bool = Field(description="True when the company's loop for this role has the round.")
    round_name: str | None = Field(default=None, description="The round's name in the loop.")
    acting_as: ActingAs


class SuggestedInterviews(BaseModel):
    """TG-3: Strova's suggested interviews for a role, usual ones first."""

    company_mode: str = Field(description="curated or generic")
    items: list[SuggestedInterview]


class InterviewsCreate(BaseModel):
    """RH-1, TG-3: the types the user keeps. Each becomes an interview of the role."""

    resume_id: uuid.UUID | None = Field(
        default=None, description="RM-2: default is the user's main resume."
    )
    interview_types: list[InterviewType] = Field(min_length=1)
    custom: CustomSessionSpec | None = Field(
        default=None, description="CU-1: the Custom setup, required when Custom is kept."
    )


class InterviewOut(BaseModel):
    id: uuid.UUID
    job_target_id: uuid.UUID
    resume_id: uuid.UUID
    interview_type: InterviewType
    custom: CustomSessionSpec | None
    created_at: datetime
    archived_at: datetime | None
    acting_as: ActingAs


class InterviewTakeOut(BaseModel):
    """One take: a session of this interview."""

    number: int = Field(description="Take 1 is the first, in time order.")
    session_id: uuid.UUID
    mode: Mode
    status: SessionStatus
    at: datetime
    duration_min: int
    hire_signal: HireSignal | None
    met_bar: int | None = Field(description="DB-2: answers that met the bar. None until scored.")
    scored: int | None = Field(description="Answers scored. None until scored.")
    counts: bool = Field(description="RH-2: counts toward readiness.")


class RoleSummary(BaseModel):
    id: uuid.UUID
    name: str | None
    title: str | None
    company_name: str | None
    company_mode: str
    interview_date: date | None
    days_left: int | None
    archived: bool


class InterviewWithReadiness(BaseModel):
    interview: InterviewOut
    readiness: InterviewReadiness
    takes_count: int
    last_signal: HireSignal | None


class InterviewDetail(InterviewWithReadiness):
    """RH-3: everything the interview page shows."""

    role: RoleSummary
    resume_name: str | None
    takes: list[InterviewTakeOut] = Field(description="Newest first.")


class RoleOut(BaseModel):
    """TG-1: a role with one readiness per interview."""

    role: RoleSummary
    interviews: list[InterviewWithReadiness]


class RehearsalItem(InterviewWithReadiness):
    role: RoleSummary


class Rehearsals(BaseModel):
    """RH-4: every interview across roles and the recommended next take."""

    items: list[RehearsalItem]
    next_interview_id: uuid.UUID | None = Field(
        description="Closest interview date first, then lowest readiness below 75. None when "
        "every interview is at the goal."
    )


# --- rules ---------------------------------------------------------------------------------


def _posting(target: JobTarget) -> JobPosting | None:
    return JobPosting.model_validate(target.parsed_json) if target.parsed_json else None


def _company(profile: ResolvedProfile, target: JobTarget) -> str | None:
    posting = _posting(target)
    if profile.generic:
        return None
    return profile.company_name or (posting.company_name if posting else None)


def _loop_rounds(
    profile: ResolvedProfile, target: JobTarget, family: RoleFamily | None = None
) -> list[tuple[InterviewType, str, str | None]]:
    """(type, round name, interviewer role) for each simulated round of the role's loop."""
    if profile.profile is None or _posting(target) is None:
        return []
    wanted = _family(target, family)
    rounds: list[tuple[InterviewType, str, str | None]] = []
    for loop in profile.profile.loop_structure:
        if loop.role_family != wanted:
            continue
        for r in loop.rounds:
            if r.interview_type is not None and all(r.interview_type != x[0] for x in rounds):
                rounds.append((InterviewType(r.interview_type), r.name, r.interviewer_role))
    return rounds


def acting_as(
    profile: ResolvedProfile,
    target: JobTarget,
    kind: InterviewType,
    family: RoleFamily | None = None,
) -> ActingAs:
    """ux-spec section 4.1: the profile's interviewer for that round, else the family's title for
    the type (RF-9)."""
    rounds = _loop_rounds(profile, target, family)
    named = next((role for t, _, role in rounds if t == kind and role), None)
    title = named or family_info(_family(target, family)).interviewer_title(kind)
    company = _company(profile, target)
    text = (
        f"Strova is acting as {title} at {company}"
        if company
        else f"Strova is acting as {'an' if title[:1].lower() in 'aeiou' else 'a'} {title}"
    )
    return ActingAs(title=title, company=company, text=text)


def suggested(
    profile: ResolvedProfile, target: JobTarget, family: RoleFamily | None = None
) -> SuggestedInterviews:
    """TG-3: the loop's rounds (usual), then the other types. Without a loop for the job's
    family: that family's generic loop (RF-9). `family` previews an unsaved edit (RF-10)."""
    rounds = _loop_rounds(profile, target, family)
    loop = family_info(_family(target, family)).generic_loop
    usual = [t for t, _, _ in rounds] if rounds else list(loop)
    names = {t: name for t, name, _ in rounds}
    others = [
        t
        for t in (
            InterviewType.BEHAVIORAL,
            InterviewType.HIRING_MANAGER,
            InterviewType.TECHNICAL_QA,
            InterviewType.CASE,
            InterviewType.RECRUITER_SCREEN,
        )
        if t not in usual
    ]
    items = [
        SuggestedInterview(
            interview_type=t,
            description=DESCRIPTIONS[t],
            usual=t in usual,
            round_name=names.get(t),
            acting_as=acting_as(profile, target, t, family),
        )
        for t in [*usual, *others]
    ]
    return SuggestedInterviews(
        company_mode="generic" if profile.generic else "curated", items=items
    )


def interview_competencies(row: TargetInterview) -> list[Competency]:
    """The competencies of the interview type; for Custom, those of its question categories."""
    if row.interview_type == InterviewType.CUSTOM:
        if not row.custom_json:
            return []
        return list(CustomSessionSpec.model_validate(row.custom_json).competencies())
    return list(COMPETENCIES_BY_TYPE.get(row.interview_type, ()))


@dataclass(frozen=True)
class Take:
    session: InterviewSession
    card: Scorecard | None

    @property
    def at(self) -> datetime:
        return self.session.started_at or self.session.created_at

    @property
    def counts(self) -> bool:
        profile = self.session.model_profile
        return (
            self.card is not None
            and self.session.mode == Mode.REALISTIC
            and profile is not None
            and profile not in DEV_PROFILES
        )


def _score(
    counted: list[Take], competencies: list[Competency]
) -> tuple[int | None, list[CompetencyReadiness]]:
    """RH-2 over counted takes, newest first: the most recent score per competency."""
    latest: dict[Competency, int] = {}
    for take in counted[:TAKES_COUNTED]:
        assert take.card is not None
        for s in take.card.competency_scores:
            if s.competency in competencies and s.competency not in latest:
                latest[s.competency] = s.score
    rows = [CompetencyReadiness(competency=c, score=latest.get(c)) for c in competencies]
    scores = list(latest.values())
    if not scores:
        return None, rows
    mean = sum(scores) / len(scores)
    return round((mean - 1) / 3 * 100), rows


def readiness(row: TargetInterview, takes: list[Take]) -> InterviewReadiness:
    """RH-2: takes newest first."""
    competencies = interview_competencies(row)
    counted = [t for t in takes if t.counts]
    score, rows = _score(counted, competencies)
    before, _ = _score(counted[1:], competencies)
    return InterviewReadiness(
        interview_id=row.id,
        score=score,
        goal=READINESS_GOAL,
        competencies=rows,
        change=score - before if score is not None and before is not None else None,
        takes_counted=min(len(counted), TAKES_COUNTED),
    )


# --- data ----------------------------------------------------------------------------------


async def _takes(db: AsyncSession, row: TargetInterview) -> list[Take]:
    """The interview's sessions (same job, resume and type), newest first."""
    result = await db.execute(
        select(InterviewSession, ScorecardRow)
        .outerjoin(ScorecardRow, ScorecardRow.session_id == InterviewSession.id)
        .where(
            InterviewSession.org_id == row.org_id,
            InterviewSession.job_target_id == row.job_target_id,
            InterviewSession.resume_id == row.resume_id,
            InterviewSession.type == row.interview_type,
        )
    )
    takes = [
        Take(
            session,
            Scorecard(
                hire_signal=card.hire_signal,
                rationale=card.rationale,
                competency_scores=card.competency_scores_json,
                value_scores=card.value_scores_json,
                per_question=card.per_question_json,
                scorer_model=card.scorer_model,
                rubric_version=card.rubric_version,
            )
            if card is not None
            else None,
        )
        for session, card in result.all()
    ]
    return sorted(takes, key=lambda t: (t.at, str(t.session.id)), reverse=True)


def _take_out(take: Take, number: int) -> InterviewTakeOut:
    bar = answers_at_bar(take.card) if take.card else None
    return InterviewTakeOut(
        number=number,
        session_id=take.session.id,
        mode=take.session.mode,
        status=take.session.status,
        at=take.at,
        duration_min=take.session.duration_min,
        hire_signal=take.card.hire_signal if take.card else None,
        met_bar=bar.met if bar else None,
        scored=bar.scored if bar else None,
        counts=take.counts,
    )


def _interview_out(
    row: TargetInterview, profile: ResolvedProfile, target: JobTarget
) -> InterviewOut:
    return InterviewOut(
        id=row.id,
        job_target_id=row.job_target_id,
        resume_id=row.resume_id,
        interview_type=row.interview_type,
        custom=CustomSessionSpec.model_validate(row.custom_json) if row.custom_json else None,
        created_at=row.created_at,
        archived_at=row.archived_at,
        acting_as=acting_as(profile, target, row.interview_type),
    )


def _role_summary(target: JobTarget, profile: ResolvedProfile) -> RoleSummary:
    posting = _posting(target)
    return RoleSummary(
        id=target.id,
        name=job_target_name(target),
        title=posting.title if posting else None,
        company_name=profile.company_name or (posting.company_name if posting else None),
        company_mode="generic" if profile.generic else "curated",
        interview_date=target.interview_date,
        days_left=service.days_left(target.interview_date),
        archived=target.archived_at is not None,
    )


async def _with_readiness(
    db: AsyncSession, row: TargetInterview, profile: ResolvedProfile, target: JobTarget
) -> tuple[InterviewWithReadiness, list[Take]]:
    takes = await _takes(db, row)
    last = next((t.card.hire_signal for t in takes if t.card is not None), None)
    return (
        InterviewWithReadiness(
            interview=_interview_out(row, profile, target),
            readiness=readiness(row, takes),
            takes_count=len(takes),
            last_signal=last,
        ),
        takes,
    )


async def _owned_interview(db: AsyncSession, me: Me, interview_id: uuid.UUID) -> TargetInterview:
    row = await db.scalar(
        select(TargetInterview).where(
            TargetInterview.id == interview_id,
            TargetInterview.org_id == me.org_id,
            TargetInterview.user_id == me.user_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Interview not found")
    return row


async def _role_interviews(db: AsyncSession, target: JobTarget) -> list[TargetInterview]:
    rows = await db.scalars(
        select(TargetInterview)
        .where(TargetInterview.job_target_id == target.id, TargetInterview.archived_at.is_(None))
        .order_by(TargetInterview.created_at, TargetInterview.id)
    )
    return list(rows)


async def _main_resume(db: AsyncSession, me: Me) -> ResumeRow | None:
    return await db.scalar(
        select(ResumeRow)
        .where(
            ResumeRow.org_id == me.org_id,
            ResumeRow.user_id == me.user_id,
            ResumeRow.deleted_at.is_(None),
        )
        .order_by(ResumeRow.is_main.desc(), ResumeRow.uploaded_at.desc())
        .limit(1)
    )


async def create_interviews(
    db: AsyncSession, me: Me, target: JobTarget, body: InterviewsCreate
) -> list[TargetInterview]:
    """RH-1: one interview per kept type. A type the role already has for that resume is reused,
    so the call is safe to repeat. The caller commits."""
    if body.resume_id is not None:
        resume = await db.scalar(
            select(ResumeRow).where(
                ResumeRow.id == body.resume_id,
                ResumeRow.org_id == me.org_id,
                ResumeRow.user_id == me.user_id,
                ResumeRow.deleted_at.is_(None),
            )
        )
    else:
        resume = await _main_resume(db, me)
    if resume is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Add a resume first.")
    if InterviewType.CUSTOM in body.interview_types and body.custom is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Custom needs its setup (custom)."
        )
    existing = {
        r.interview_type: r for r in await _role_interviews(db, target) if r.resume_id == resume.id
    }
    out: list[TargetInterview] = []
    for kind in dict.fromkeys(body.interview_types):
        row = existing.get(kind)
        if row is None:
            row = TargetInterview(
                org_id=me.org_id,
                user_id=me.user_id,
                job_target_id=target.id,
                resume_id=resume.id,
                interview_type=kind,
                custom_json=body.custom.model_dump(mode="json")
                if kind == InterviewType.CUSTOM and body.custom
                else None,
                created_at=datetime.now(UTC),
            )
            db.add(row)
        out.append(row)
    await db.flush()
    return out


async def interview_for_session(
    db: AsyncSession, me: Me, interview_id: uuid.UUID
) -> TargetInterview:
    """The live interview a new take runs for (sessions create path)."""
    row = await _owned_interview(db, me, interview_id)
    if row.archived_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Interview not found")
    return row


# --- endpoints -----------------------------------------------------------------------------


@router.get("/roles/{job_target_id}/suggested-interviews")
async def suggested_interviews(
    job_target_id: uuid.UUID, db: Db, me: Me, role_family: RoleFamily | None = None
) -> SuggestedInterviews:
    """TG-3: the company's usual rounds for this role (the family's generic loop in generic
    mode). `role_family` previews the family the user picked on the check step before the role
    is saved (RF-10); nothing is stored."""
    target = await _owned_job_target(db, me, job_target_id, live=True)
    if target.parsed_json is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The job posting is still being read.")
    return suggested(await resolve_profile(db, target.company_id), target, role_family)


@router.get("/roles/{job_target_id}/interviews")
async def list_interviews(job_target_id: uuid.UUID, db: Db, me: Me) -> list[InterviewWithReadiness]:
    target = await _owned_job_target(db, me, job_target_id)
    profile = await resolve_profile(db, target.company_id)
    return [
        (await _with_readiness(db, row, profile, target))[0]
        for row in await _role_interviews(db, target)
    ]


@router.post("/roles/{job_target_id}/interviews", status_code=status.HTTP_201_CREATED)
async def add_interviews(
    job_target_id: uuid.UUID, body: InterviewsCreate, db: Db, me: Me
) -> list[InterviewOut]:
    """RH-1, TG-3: keep the chosen types as interviews of the role."""
    target = await _owned_job_target(db, me, job_target_id, live=True)
    rows = await create_interviews(db, me, target, body)
    await db.commit()
    profile = await resolve_profile(db, target.company_id)
    return [_interview_out(r, profile, target) for r in rows]


@router.delete("/interviews/{interview_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_interview(interview_id: uuid.UUID, db: Db, me: Me) -> Response:
    """RH-1: remove an interview from the role. Its takes and debriefs stay."""
    row = await _owned_interview(db, me, interview_id)
    if row.archived_at is None:
        row.archived_at = datetime.now(UTC)
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/interviews/{interview_id}")
async def get_interview(interview_id: uuid.UUID, db: Db, me: Me) -> InterviewDetail:
    """RH-2, RH-3: the interview, its role, readiness and takes."""
    row = await _owned_interview(db, me, interview_id)
    target = await db.get(JobTarget, row.job_target_id)
    assert target is not None
    profile = await resolve_profile(db, target.company_id)
    summary, takes = await _with_readiness(db, row, profile, target)
    resume = await db.get(ResumeRow, row.resume_id)
    total = len(takes)
    return InterviewDetail(
        **summary.model_dump(),
        role=_role_summary(target, profile),
        resume_name=(resume.name if resume and resume.deleted_at is None else None),
        takes=[_take_out(t, total - i) for i, t in enumerate(takes)],
    )


async def _live_roles(db: AsyncSession, me: Me) -> list[JobTarget]:
    rows = await db.scalars(
        select(JobTarget)
        .where(
            JobTarget.org_id == me.org_id,
            JobTarget.user_id == me.user_id,
            JobTarget.deleted_at.is_(None),
            JobTarget.archived_at.is_(None),
        )
        .order_by(JobTarget.created_at.desc())
    )
    return list(rows)


@router.get("/roles")
async def list_roles(db: Db, me: Me) -> list[RoleOut]:
    """TG-1: every live role, newest first, with one readiness per interview."""
    out: list[RoleOut] = []
    for target in await _live_roles(db, me):
        profile = await resolve_profile(db, target.company_id)
        interviews = [
            (await _with_readiness(db, row, profile, target))[0]
            for row in await _role_interviews(db, target)
        ]
        out.append(RoleOut(role=_role_summary(target, profile), interviews=interviews))
    return out


def recommend(items: list[RehearsalItem]) -> uuid.UUID | None:
    """RH-4: closest interview date first, then lowest readiness below the goal."""
    below = [i for i in items if i.readiness.score is None or i.readiness.score < READINESS_GOAL]
    if not below:
        return None

    def key(i: RehearsalItem) -> tuple[bool, date, int, datetime]:
        when = i.role.interview_date
        return (
            when is None,
            when or date.max,
            -1 if i.readiness.score is None else i.readiness.score,
            i.interview.created_at,
        )

    return min(below, key=key).interview.id


@router.get("/rehearsals")
async def rehearsals(db: Db, me: Me) -> Rehearsals:
    """RH-4: every interview across live roles and the recommended next take."""
    items: list[RehearsalItem] = []
    for target in await _live_roles(db, me):
        profile = await resolve_profile(db, target.company_id)
        role = _role_summary(target, profile)
        for row in await _role_interviews(db, target):
            summary, _ = await _with_readiness(db, row, profile, target)
            items.append(RehearsalItem(**summary.model_dump(), role=role))
    return Rehearsals(items=items, next_interview_id=recommend(items))
