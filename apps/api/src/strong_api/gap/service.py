"""Start, read and refresh gap analyses (GA-1 to GA-4).

A run is a gap_analyses row. The API creates it with status "running" and enqueues the worker
job, which sets "ready" or "failed". A row records what it was built from:

- input_hash: the posting, the job context (IN-4) and the resume, hashed here
- profile_version: the company profile version the worker used (NULL in generic mode)

When either no longer matches, the row is stale. Editing the job or the resume starts a new run
for the job targets they affect (recompute), within the rate limit.

Gap analysis is free (GA-4): nothing here touches plan minutes or usage records. It is rate
limited per user instead.

RC-7: a resume comparison makes rows with purpose "comparison". They are never the role's latest
analysis, and a comparison that starts any of them counts as one run against the rate limit. A
role row copied from a comparison row (source_gap_id) made no model call and does not count.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.gap.schemas import GapAnalysisOut
from strong_api.gap.settings import GapSettings
from strong_api.inputs.queue import RUN_GAP_ANALYSIS, JobQueue
from strong_core.db.models import GapAnalysis as GapRow
from strong_core.db.models import JobTarget, ResumeComparison
from strong_core.db.models import Resume as ResumeRow
from strong_core.library import default_resume_name
from strong_core.profiles import resolve_profile
from strong_core.schemas import GapAnalysis, GapPurpose, GapStatus

TIMED_OUT = "The analysis took too long. Start it again."


class RateLimitedError(Exception):
    def __init__(self, retry_after_s: int, limit: str) -> None:
        self.retry_after_s = retry_after_s
        self.limit = limit
        super().__init__(f"rate limited ({limit}), retry after {retry_after_s} s")


def utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; Postgres returns aware ones. Compare in UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def input_hash(target: JobTarget, resume: ResumeRow) -> str:
    data = {
        "posting": target.parsed_json,
        "stage": target.stage,
        "context": target.context_notes,
        "resume": resume.parsed_json,
    }
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def resume_label(resume: ResumeRow) -> str:
    return resume.name or default_resume_name(None, resume.uploaded_at)


async def latest(db: AsyncSession, job_target_id: uuid.UUID) -> GapRow | None:
    """The role's own latest analysis, in any status. Never a comparison row (RC-7)."""
    return await db.scalar(
        select(GapRow)
        .where(GapRow.job_target_id == job_target_id, GapRow.purpose == GapPurpose.ROLE)
        .order_by(GapRow.created_at.desc(), GapRow.updated_at.desc().nulls_last())
        .limit(1)
    )


async def check_rate_limit(
    db: AsyncSession, user_id: uuid.UUID, settings: GapSettings, now: datetime | None = None
) -> None:
    """Raise RateLimitedError when the user started too many runs (GA-4, BL-2).

    A run is a role row the worker computes, or a resume comparison that started any analysis
    (RC-7: one run however many resumes it compares). Comparison rows and copied role rows are
    not counted on their own.
    """
    now = now or datetime.now(UTC)
    rows = await db.scalars(
        select(GapRow.created_at)
        .join(JobTarget, JobTarget.id == GapRow.job_target_id)
        .where(
            JobTarget.user_id == user_id,
            GapRow.purpose == GapPurpose.ROLE,
            GapRow.source_gap_id.is_(None),
        )
        .order_by(GapRow.created_at.desc())
        .limit(settings.gap_rate_limit_per_day)
    )
    comparisons = await db.scalars(
        select(ResumeComparison.created_at)
        .where(ResumeComparison.user_id == user_id, ResumeComparison.new_runs > 0)
        .order_by(ResumeComparison.created_at.desc())
        .limit(settings.gap_rate_limit_per_day)
    )
    times = [utc(t) for t in rows] + [utc(t) for t in comparisons]
    windows = (
        ("hour", timedelta(hours=1), settings.gap_rate_limit_per_hour),
        ("day", timedelta(days=1), settings.gap_rate_limit_per_day),
    )
    for name, window, limit in windows:
        recent = sorted(t for t in times if t > now - window)
        if len(recent) >= limit:
            oldest = recent[len(recent) - limit]
            retry = int((oldest + window - now).total_seconds()) + 1
            raise RateLimitedError(max(retry, 1), f"{limit} per {name}")


def timed_out(row: GapRow, settings: GapSettings, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    age = now - utc(row.created_at)
    return row.status == GapStatus.RUNNING and age > timedelta(
        seconds=settings.gap_running_timeout_s
    )


async def start(
    db: AsyncSession,
    queue: JobQueue,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    target: JobTarget,
    resume: ResumeRow,
    settings: GapSettings,
    reuse_ready: bool = False,
) -> GapRow:
    """Start a run, or return the one already running for the same inputs.

    With reuse_ready (R1), a ready run for the same inputs and company profile is returned too,
    so picking a saved job and a saved CV again does not build the same analysis twice.
    """
    digest = input_hash(target, resume)
    current = await latest(db, target.id)
    if (
        current is not None
        and current.status == GapStatus.RUNNING
        and current.resume_id == resume.id
        and current.input_hash == digest
        and not timed_out(current, settings)
    ):
        return current
    if (
        reuse_ready
        and current is not None
        and current.status == GapStatus.READY
        and current.resume_id == resume.id
        and not await is_stale(db, current, target, resume)
    ):
        return current
    if reuse_ready:
        copied = await copy_from_comparison(db, target, resume, digest)
        if copied is not None:
            return copied
    await check_rate_limit(db, user_id, settings)
    row = GapRow(
        org_id=org_id,
        job_target_id=target.id,
        resume_id=resume.id,
        status=GapStatus.RUNNING,
        input_hash=digest,
        created_at=datetime.now(UTC),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await queue.enqueue(
        RUN_GAP_ANALYSIS, f"ga:{row.id}", gap_analysis_id=str(row.id), org_id=str(org_id)
    )
    await db.refresh(row)
    return row


def copy_row(row: GapRow, now: datetime) -> GapRow:
    """RC-6: a role row with the analysis of `row`, made without a model call. It does not count
    against the rate limit (source_gap_id is set). The caller adds and commits it."""
    return GapRow(
        org_id=row.org_id,
        job_target_id=row.job_target_id,
        resume_id=row.resume_id,
        status=GapStatus.READY,
        input_hash=row.input_hash,
        profile_version=row.profile_version,
        match_score=row.match_score,
        breakdown_json=row.breakdown_json,
        session_plan_json=row.session_plan_json,
        model_version=row.model_version,
        purpose=GapPurpose.ROLE,
        source_gap_id=row.id,
        created_at=now,
        updated_at=now,
    )


async def copy_from_comparison(
    db: AsyncSession, target: JobTarget, resume: ResumeRow, digest: str
) -> GapRow | None:
    """RC-6: when a resume comparison already analysed this job and resume (ready, not stale),
    the role's analysis is a copy of it, so creating the role after comparing costs no run."""
    found = await db.scalar(
        select(GapRow)
        .where(
            GapRow.job_target_id == target.id,
            GapRow.resume_id == resume.id,
            GapRow.purpose == GapPurpose.COMPARISON,
            GapRow.status == GapStatus.READY,
            GapRow.input_hash == digest,
            GapRow.breakdown_json.is_not(None),
        )
        .order_by(GapRow.created_at.desc(), GapRow.id.desc())
        .limit(1)
    )
    if found is None or await is_stale(db, found, target, resume):
        return None
    row = copy_row(found, datetime.now(UTC))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def is_stale(db: AsyncSession, row: GapRow, target: JobTarget, resume: ResumeRow) -> bool:
    if row.input_hash != input_hash(target, resume):
        return True
    if row.status != GapStatus.READY:
        return False
    profile = await resolve_profile(db, target.company_id)
    return profile.version != row.profile_version


async def recompute(
    db: AsyncSession,
    queue: JobQueue,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    settings: GapSettings,
    job_target_id: uuid.UUID | None = None,
    resume_id: uuid.UUID | None = None,
) -> int:
    """After an edit: start a new run for each affected job target whose latest run is stale.

    Affected means the edited job target, or every job target whose latest run used the edited
    resume. Runs over the rate limit are skipped; those analyses stay stale until the user
    starts them again. Returns the number of runs started.
    """
    query = select(JobTarget).where(JobTarget.org_id == org_id, JobTarget.deleted_at.is_(None))
    if job_target_id is not None:
        query = query.where(JobTarget.id == job_target_id)
    started = 0
    for target in (await db.scalars(query)).all():
        row = await latest(db, target.id)
        if row is None or (resume_id is not None and row.resume_id != resume_id):
            continue
        if target.parsed_json is None:
            continue
        resume = await db.get(ResumeRow, row.resume_id)
        if resume is None or resume.parsed_json is None or resume.deleted_at is not None:
            continue
        if not await is_stale(db, row, target, resume):
            continue
        try:
            await start(
                db,
                queue,
                org_id=org_id,
                user_id=user_id,
                target=target,
                resume=resume,
                settings=settings,
            )
        except RateLimitedError:
            break
        started += 1
    return started


async def to_out(
    db: AsyncSession, row: GapRow, target: JobTarget, settings: GapSettings
) -> GapAnalysisOut:
    resume = await db.get(ResumeRow, row.resume_id)
    job_deleted = target.deleted_at is not None
    resume_deleted = resume is None or resume.deleted_at is not None
    # R1: a deleted job or CV cannot be analysed again, so the report is never "stale".
    stale = False
    if not job_deleted and resume is not None and resume.deleted_at is None:
        stale = await is_stale(db, row, target, resume)
    status, error = row.status, row.error
    if timed_out(row, settings):
        status, error = GapStatus.FAILED, TIMED_OUT
    ready = status == GapStatus.READY and row.breakdown_json is not None
    return GapAnalysisOut(
        id=row.id,
        job_target_id=row.job_target_id,
        resume_id=row.resume_id,
        resume_name=resume_label(resume) if resume is not None and not resume_deleted else None,
        resume_deleted=resume_deleted,
        job_deleted=job_deleted,
        status=status,
        analysis=GapAnalysis.model_validate(row.breakdown_json) if ready else None,
        error=error,
        generic_mode=(row.profile_version is None) if ready else None,
        profile_version=row.profile_version,
        stale=stale,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
