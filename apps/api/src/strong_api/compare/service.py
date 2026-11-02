"""Start, read and act on resume comparisons (RC-1 to RC-8).

A comparison is a resume_comparisons row. Each entry points at the gap analysis a resume is
ranked by: a reused one when the same job and resume were already analysed (any purpose, ready
and not stale, or still running), else a new gap_analyses row with purpose "comparison" that the
normal worker job computes. Ranking, the reason and the gap hints are computed here when the
comparison is read (strong_api.compare.ranking), so the comparison itself makes no model call.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.compare import ranking
from strong_api.compare.schemas import (
    ComparedResume,
    ComparisonGap,
    HintSource,
    ResumeComparisonOut,
)
from strong_api.gap import service as gap_service
from strong_api.gap.settings import GapSettings
from strong_api.inputs.deps import CurrentUser
from strong_api.inputs.limits import MAX_RESUMES_PER_USER
from strong_api.inputs.queue import RUN_GAP_ANALYSIS, JobQueue
from strong_core.db.models import GapAnalysis as GapRow
from strong_core.db.models import JobTarget, ResumeComparison, TargetInterview
from strong_core.db.models import Resume as ResumeRow
from strong_core.schemas import (
    GapAnalysis,
    GapPurpose,
    GapStatus,
    JobPosting,
    Resume,
    ResumeComparisonEntry,
)

MIN_RESUMES = 2


class TooFewResumesError(Exception):
    pass


def now() -> datetime:
    return datetime.now(UTC)


async def eligible_resumes(db: AsyncSession, me: CurrentUser) -> list[ResumeRow]:
    """RC-2: the user's live, read resumes, main first, then newest; at most the resume limit."""
    rows = await db.scalars(
        select(ResumeRow)
        .where(
            ResumeRow.org_id == me.org_id,
            ResumeRow.user_id == me.user_id,
            ResumeRow.deleted_at.is_(None),
            ResumeRow.parsed_json.is_not(None),
        )
        .order_by(ResumeRow.is_main.desc(), ResumeRow.uploaded_at.desc(), ResumeRow.id)
        .limit(MAX_RESUMES_PER_USER)
    )
    return list(rows)


async def reusable(
    db: AsyncSession, target: JobTarget, resume: ResumeRow, settings: GapSettings
) -> GapRow | None:
    """RC-2: an analysis of the same job and resume that needs no new run: ready and not stale,
    or still running for the same inputs. Any purpose."""
    digest = gap_service.input_hash(target, resume)
    rows = await db.scalars(
        select(GapRow)
        .where(
            GapRow.job_target_id == target.id,
            GapRow.resume_id == resume.id,
            GapRow.input_hash == digest,
            GapRow.status != GapStatus.FAILED,
        )
        .order_by(GapRow.created_at.desc(), GapRow.id.desc())
        .limit(5)
    )
    for row in rows:
        if row.status == GapStatus.RUNNING and not gap_service.timed_out(row, settings):
            return row
        if (
            row.status == GapStatus.READY
            and row.breakdown_json is not None
            and not await gap_service.is_stale(db, row, target, resume)
        ):
            return row
    return None


async def start(
    db: AsyncSession,
    queue: JobQueue,
    *,
    me: CurrentUser,
    target: JobTarget,
    settings: GapSettings,
) -> ResumeComparison:
    """RC-2, RC-7: compare every eligible resume. Raises TooFewResumesError and
    gap_service.RateLimitedError (only when a new analysis is needed)."""
    resumes = await eligible_resumes(db, me)
    if len(resumes) < MIN_RESUMES:
        raise TooFewResumesError
    plan = [(resume, await reusable(db, target, resume, settings)) for resume in resumes]
    needed = sum(1 for _, row in plan if row is None)
    if needed:
        await gap_service.check_rate_limit(db, me.user_id, settings)
    started = now()
    comparison = ResumeComparison(
        org_id=me.org_id,
        user_id=me.user_id,
        job_target_id=target.id,
        entries_json=[],
        new_runs=needed,
        created_at=started,
    )
    db.add(comparison)
    entries: list[ResumeComparisonEntry] = []
    new_rows: list[GapRow] = []
    for resume, found in plan:
        row = found
        if row is None:
            row = GapRow(
                org_id=me.org_id,
                job_target_id=target.id,
                resume_id=resume.id,
                status=GapStatus.RUNNING,
                input_hash=gap_service.input_hash(target, resume),
                purpose=GapPurpose.COMPARISON,
                created_at=started,
            )
            db.add(row)
            await db.flush()
            new_rows.append(row)
        entries.append(
            ResumeComparisonEntry(
                resume_id=resume.id, gap_analysis_id=row.id, reused=found is not None
            )
        )
    comparison.entries_json = [e.model_dump(mode="json") for e in entries]
    await db.commit()
    await db.refresh(comparison)
    for row in new_rows:
        await queue.enqueue(
            RUN_GAP_ANALYSIS, f"ga:{row.id}", gap_analysis_id=str(row.id), org_id=str(me.org_id)
        )
    return comparison


async def latest(db: AsyncSession, job_target_id: uuid.UUID) -> ResumeComparison | None:
    return await db.scalar(
        select(ResumeComparison)
        .where(ResumeComparison.job_target_id == job_target_id)
        .order_by(ResumeComparison.created_at.desc(), ResumeComparison.id.desc())
        .limit(1)
    )


def entries_of(comparison: ResumeComparison) -> list[ResumeComparisonEntry]:
    return [ResumeComparisonEntry.model_validate(e) for e in comparison.entries_json]


async def role_resume_id(db: AsyncSession, target: JobTarget) -> uuid.UUID | None:
    """The resume the role uses now: its first live interview's, else its latest analysis'."""
    interview = await db.scalar(
        select(TargetInterview)
        .where(TargetInterview.job_target_id == target.id, TargetInterview.archived_at.is_(None))
        .order_by(TargetInterview.created_at, TargetInterview.id)
        .limit(1)
    )
    if interview is not None:
        return interview.resume_id
    row = await gap_service.latest(db, target.id)
    return row.resume_id if row is not None else None


def _posting(target: JobTarget) -> JobPosting | None:
    if target.parsed_json is None or target.deleted_at is not None:
        return None
    try:
        return JobPosting.model_validate(target.parsed_json)
    except ValidationError:
        return None


class Loaded:
    """A comparison with its rows loaded, for reading and for the actions."""

    def __init__(self) -> None:
        self.candidates: list[ranking.Candidate] = []
        self.out: list[ComparedResume] = []
        self.resume_rows: dict[uuid.UUID, ResumeRow] = {}
        self.gap_rows: dict[uuid.UUID, GapRow] = {}
        self.running = False
        self.stale_names: list[str] = []
        self.deleted = False


async def load(
    db: AsyncSession, comparison: ResumeComparison, target: JobTarget, settings: GapSettings
) -> Loaded:
    loaded = Loaded()
    posting = _posting(target)
    for entry in entries_of(comparison):
        resume_row = await db.get(ResumeRow, entry.resume_id)
        row = await db.get(GapRow, entry.gap_analysis_id)
        if row is None:
            continue
        deleted = resume_row is None or resume_row.deleted_at is not None
        parsed = None
        if not deleted and resume_row is not None and resume_row.parsed_json is not None:
            parsed = Resume.model_validate(resume_row.parsed_json)
            loaded.resume_rows[entry.resume_id] = resume_row
        loaded.gap_rows[entry.resume_id] = row
        status, error = row.status, row.error
        if gap_service.timed_out(row, settings):
            status, error = GapStatus.FAILED, gap_service.TIMED_OUT
        analysis = None
        if status == GapStatus.READY and row.breakdown_json is not None:
            analysis = GapAnalysis.model_validate(row.breakdown_json)
        loaded.running = loaded.running or status == GapStatus.RUNNING
        name = gap_service.resume_label(resume_row) if resume_row and not deleted else "Resume"
        stale = False
        if resume_row is not None and not deleted and target.deleted_at is None:
            stale = await gap_service.is_stale(db, row, target, resume_row)
        if stale:
            loaded.stale_names.append(name)
        loaded.deleted = loaded.deleted or deleted
        candidate = ranking.Candidate(
            resume_id=entry.resume_id,
            name=name,
            is_main=bool(resume_row and resume_row.is_main and not deleted),
            resume=parsed,
            analysis=analysis,
        )
        ranking.prescreen(candidate, posting)
        loaded.candidates.append(candidate)
        loaded.out.append(
            ComparedResume(
                resume_id=entry.resume_id,
                resume_name=None if deleted else name,
                is_main=candidate.is_main,
                deleted=deleted,
                gap_analysis_id=row.id,
                status=status,
                error=error,
                reused=entry.reused,
                match_score=analysis.match_score if analysis else None,
                must_haves_total=candidate.must_total,
                must_haves_shown=candidate.must_shown,
                must_haves_missing=candidate.must_missing,
                high_gaps=candidate.high_gaps,
                rank=None,
                stale=stale,
            )
        )
    return loaded


def focus_and_hints(
    comparison: ResumeComparison, loaded: Loaded
) -> tuple[list[ranking.Candidate], ranking.Candidate | None, list[ranking.Hint]]:
    """The ranked candidates, the focus resume (chosen, else recommended) and its hints."""
    if loaded.running:
        return [], None, []
    order = ranking.ranked(loaded.candidates)
    if not order:
        return order, None, []
    focus = next((c for c in order if c.resume_id == comparison.chosen_resume_id), order[0])
    others = [c for c in order if c is not focus]
    return order, focus, ranking.hints(focus, others)


async def to_out(
    db: AsyncSession,
    me: CurrentUser,
    comparison: ResumeComparison,
    target: JobTarget,
    settings: GapSettings,
) -> ResumeComparisonOut:
    loaded = await load(db, comparison, target, settings)
    order, focus, hints = focus_and_hints(comparison, loaded)
    ranks = {c.resume_id: i + 1 for i, c in enumerate(order)}
    resumes = [r.model_copy(update={"rank": ranks.get(r.resume_id)}) for r in loaded.out]
    resumes.sort(key=lambda r: (r.rank is None, r.rank or 0))
    if loaded.running:
        status = "running"
    elif order:
        status = "ready"
    else:
        status = "failed"
    applied = set(comparison.applied_json or [])
    dismissed = set(comparison.dismissed_json or [])
    gaps = [
        ComparisonGap(
            key=h.key,
            summary=h.summary,
            severity=h.severity,
            related_requirement=h.related_requirement,
            source=HintSource(**vars(h.source)) if h.source else None,
            status="added" if h.key in applied else "dismissed" if h.key in dismissed else "open",
        )
        for h in hints
    ]
    reason = None
    if order:
        reason = ranking.reason(order)
    out_of_date_reason = await _out_of_date(db, me, comparison, loaded)
    return ResumeComparisonOut(
        id=comparison.id,
        job_target_id=comparison.job_target_id,
        status=status,
        resumes=resumes,
        recommended_resume_id=order[0].resume_id if order else None,
        reason=reason,
        focus_resume_id=focus.resume_id if focus else None,
        gaps=gaps,
        role_resume_id=await role_resume_id(db, target),
        chosen_resume_id=comparison.chosen_resume_id,
        new_runs=comparison.new_runs,
        out_of_date=out_of_date_reason is not None,
        out_of_date_reason=out_of_date_reason,
        created_at=comparison.created_at,
    )


async def _out_of_date(
    db: AsyncSession, me: CurrentUser, comparison: ResumeComparison, loaded: Loaded
) -> str | None:
    """RC-8: why the comparison no longer matches the job and the resumes, or None."""
    if loaded.stale_names:
        return f"The job or {ranking.names(loaded.stale_names)} changed since this comparison."
    if loaded.deleted:
        return "A compared resume was deleted since this comparison."
    compared = {e.resume_id for e in entries_of(comparison)}
    current = {r.id for r in await eligible_resumes(db, me)}
    if current - compared:
        return "You added a resume since this comparison."
    return None


async def use_resume(
    db: AsyncSession,
    me: CurrentUser,
    comparison: ResumeComparison,
    target: JobTarget,
    resume: ResumeRow,
    row: GapRow,
) -> None:
    """RC-6: the role uses this resume. Its interviews move to it (the old ones are archived with
    their takes, RH-1) and its analysis becomes the role's own analysis, copied without a model
    call. The caller commits."""
    stamp = now()
    interviews = list(
        await db.scalars(
            select(TargetInterview)
            .where(
                TargetInterview.job_target_id == target.id,
                TargetInterview.archived_at.is_(None),
            )
            .order_by(TargetInterview.created_at, TargetInterview.id)
        )
    )
    have = {i.interview_type for i in interviews if i.resume_id == resume.id}
    moved: list[TargetInterview] = []
    for interview in interviews:
        if interview.resume_id == resume.id:
            continue
        interview.archived_at = stamp
        if interview.interview_type not in have:
            have.add(interview.interview_type)
            moved.append(interview)
    await db.flush()  # archive first: one live interview per role, resume and type
    for old in moved:
        db.add(
            TargetInterview(
                org_id=me.org_id,
                user_id=me.user_id,
                job_target_id=target.id,
                resume_id=resume.id,
                interview_type=old.interview_type,
                custom_json=old.custom_json,
                created_at=old.created_at,  # keeps the order of the role's interviews
            )
        )
    current = await gap_service.latest(db, target.id)
    same = (
        current is not None
        and current.resume_id == resume.id
        and current.status == GapStatus.READY
        and current.input_hash == row.input_hash
        and current.profile_version == row.profile_version
    )
    if not same:
        db.add(gap_service.copy_row(row, stamp))
    comparison.chosen_resume_id = resume.id
