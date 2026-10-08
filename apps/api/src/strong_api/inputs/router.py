"""Endpoints for job targets (IN-1, IN-2, IN-4, IN-5) and resumes (IN-3), and the library of
saved job descriptions and CVs (R1).

All routes act for the signed-in user (P3 sign-in) and only see that user's rows.

R1 library: GET /job-targets and GET /resumes list the saved, not deleted items. PATCH renames,
DELETE is a soft delete: the text, parsed data and stored file go, the row stays with
deleted_at set, so gap reports, sessions and progress that used it are kept. POST .../match
finds a saved item with the same posting text or link, or the same file content.

Create endpoints save the row and enqueue an Arq job, then return 202 with the job id. The
client polls the job endpoint until the status is "complete", then reads the job result:
outcome "extracted" (with field-level confidence and the company match), "needs_paste" (the
URL cannot be fetched; ask the user to paste the text), or "failed" (with a reason).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import func, select

from strong_api.gap import service as gap_service
from strong_api.gap.settings import GapSettings, get_gap_settings
from strong_api.inputs.deps import Db, Me, Queue
from strong_api.inputs.queue import (
    DELETE_RESUME_FILE,
    EXTRACT_JOB_TARGET,
    MATCH_JOB_TARGET,
    PARSE_RESUME,
    JobInfo,
)
from strong_api.inputs.schemas import (
    MAX_RESUME_TEXT_CHARS,
    JobContext,
    JobOut,
    JobTargetAccepted,
    JobTargetCreate,
    JobTargetMatch,
    JobTargetMatchIn,
    JobTargetOut,
    JobTargetSummary,
    JobTargetUpdate,
    LibraryRename,
    ResumeAccepted,
    ResumeMatch,
    ResumeMatchIn,
    ResumeOut,
    ResumeUpdate,
)
from strong_core.db.models import AuditLog, Company, InterviewSession, JobTarget
from strong_core.db.models import GapAnalysis as GapRow
from strong_core.db.models import Resume as ResumeRow
from strong_core.library import (
    content_hash,
    default_job_name,
    default_resume_name,
    normalize_url,
    posting_text_hash,
)
from strong_core.schemas import GapStatus, JobPosting, Resume

router = APIRouter(tags=["inputs"])

GapLimits = Annotated[GapSettings, Depends(get_gap_settings)]

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
RESUME_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
PASTE_ONLY_HOSTS = ("linkedin.com", "lnkd.in")


def _job_id(prefix: str, entity_id: uuid.UUID) -> str:
    return f"{prefix}:{entity_id}:{uuid.uuid4().hex[:12]}"


def _job_out(info: JobInfo) -> JobOut:
    return JobOut(id=info.id, status=info.status, result=info.result, error=info.error)


def _is_paste_only(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in PASTE_ONLY_HOSTS)


def _context(target: JobTarget) -> JobContext:
    if not target.context_notes:
        return JobContext()
    return JobContext.model_validate(json.loads(target.context_notes))


def _context_notes(context: JobContext) -> str | None:
    return None if context.is_empty() else context.model_dump_json(exclude_none=True)


async def _job_target_out(db: Db, target: JobTarget) -> JobTargetOut:
    slug = None
    if target.company_id is not None:
        slug = await db.scalar(select(Company.slug).where(Company.id == target.company_id))
    extracted = target.parsed_json is not None
    return JobTargetOut(
        id=target.id,
        name=job_target_name(target),
        deleted=target.deleted_at is not None,
        status="extracted" if extracted else "pending",
        source_url=target.source_url,
        posting=JobPosting.model_validate(target.parsed_json) if extracted else None,
        level=target.level,
        company_id=target.company_id,
        company_slug=slug,
        generic_mode=(target.company_id is None) if extracted else None,
        stage=target.stage,
        context=_context(target),
        created_at=target.created_at,
    )


def job_target_name(target: JobTarget) -> str | None:
    """The library name: the user's name, else the default one. None when deleted (R1)."""
    if target.deleted_at is not None:
        return None
    return target.name or default_job_name(target.parsed_json, target.source_url, target.created_at)


def resume_name(row: ResumeRow) -> str | None:
    if row.deleted_at is not None:
        return None
    return row.name or default_resume_name(None, row.uploaded_at)


def _resume_out(row: ResumeRow) -> ResumeOut:
    extracted = row.parsed_json is not None
    return ResumeOut(
        id=row.id,
        name=resume_name(row),
        deleted=row.deleted_at is not None,
        status="extracted" if extracted else "pending",
        has_file=row.file_ref is not None,
        resume=Resume.model_validate(row.parsed_json) if extracted else None,
        confirmed_at=row.confirmed_at,
        uploaded_at=row.uploaded_at,
    )


async def _owned_job_target(
    db: Db, me: Me, job_target_id: uuid.UUID, *, live: bool = False
) -> JobTarget:
    """The user's job target. With live=True a deleted one is 404 too (R1)."""
    target = await db.scalar(
        select(JobTarget).where(
            JobTarget.id == job_target_id,
            JobTarget.org_id == me.org_id,
            JobTarget.user_id == me.user_id,
        )
    )
    if target is None or (live and target.deleted_at is not None):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job target not found")
    return target


async def _owned_resume(db: Db, me: Me, resume_id: uuid.UUID, *, live: bool = False) -> ResumeRow:
    row = await db.scalar(
        select(ResumeRow).where(
            ResumeRow.id == resume_id,
            ResumeRow.org_id == me.org_id,
            ResumeRow.user_id == me.user_id,
        )
    )
    if row is None or (live and row.deleted_at is not None):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found")
    return row


def _audit(me: Me, action: str, entity: str) -> AuditLog:
    return AuditLog(org_id=me.org_id, actor=f"user:{me.user_id}", action=action, entity=entity)


# --- job targets ----------------------------------------------------------------------------


@router.post("/job-targets", status_code=status.HTTP_202_ACCEPTED)
async def create_job_target(
    body: JobTargetCreate, db: Db, me: Me, queue: Queue
) -> JobTargetAccepted:
    if body.url and not body.text and _is_paste_only(body.url):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "paste_required", "reason": "linkedin", "message": "Paste the posting text."},
        )
    target = JobTarget(
        org_id=me.org_id,
        user_id=me.user_id,
        source_url=body.url,
        raw_text=body.text,
        text_hash=posting_text_hash(body.text),
        stage=body.stage,
        context_notes=_context_notes(body.context),
    )
    db.add(target)
    await db.commit()
    await db.refresh(target)

    job_id = _job_id("jt", target.id)
    await queue.enqueue(
        EXTRACT_JOB_TARGET, job_id, job_target_id=str(target.id), org_id=str(me.org_id)
    )
    await db.refresh(target)
    return JobTargetAccepted(
        job_target=await _job_target_out(db, target), job=_job_out(await queue.info(job_id))
    )


@router.get("/job-targets")
async def list_job_targets(db: Db, me: Me) -> list[JobTargetSummary]:
    """The signed-in user's saved job targets, newest first, with dashboard numbers (PR-1).

    Deleted job descriptions are left out (R1); their reports are on GET /reports.

    match_score comes from the latest ready gap analysis. sessions_count and last_session_at
    count rows in the sessions table; they stay 0 and null until sessions exist (P7, P10).
    """
    targets = (
        await db.scalars(
            select(JobTarget)
            .where(
                JobTarget.org_id == me.org_id,
                JobTarget.user_id == me.user_id,
                JobTarget.deleted_at.is_(None),
            )
            .order_by(JobTarget.created_at.desc())
        )
    ).all()
    ids = [t.id for t in targets]
    sessions: dict[uuid.UUID, tuple[int, object]] = {}
    gaps: dict[uuid.UUID, list[GapRow]] = {}
    if ids:
        rows = await db.execute(
            select(
                InterviewSession.job_target_id,
                func.count(InterviewSession.id),
                func.max(InterviewSession.started_at),
            )
            .where(InterviewSession.job_target_id.in_(ids))
            .group_by(InterviewSession.job_target_id)
        )
        sessions = {jt: (n, last) for jt, n, last in rows}
        for gap in await db.scalars(
            select(GapRow).where(GapRow.job_target_id.in_(ids)).order_by(GapRow.created_at.desc())
        ):
            gaps.setdefault(gap.job_target_id, []).append(gap)
    out = []
    for target in targets:
        history = gaps.get(target.id, [])
        ready = next((g for g in history if g.status == GapStatus.READY), None)
        count, last = sessions.get(target.id, (0, None))
        out.append(
            JobTargetSummary(
                job_target=await _job_target_out(db, target),
                match_score=ready.match_score if ready else None,
                gap_status=history[0].status if history else None,
                sessions_count=count,
                last_session_at=last,
            )
        )
    return out


@router.post("/job-targets/match")
async def match_job_target(body: JobTargetMatchIn, db: Db, me: Me) -> JobTargetMatch:
    """R1: the saved job with the same posting text (formatting ignored) or the same link.

    Lets the app offer the saved job instead of reading the posting again. Deleted jobs and
    jobs of other users never match.
    """
    digest = posting_text_hash(body.text)
    url = normalize_url(body.url)
    if digest is None and url is None:
        return JobTargetMatch(job_target=None)
    rows = await db.scalars(
        select(JobTarget)
        .where(
            JobTarget.org_id == me.org_id,
            JobTarget.user_id == me.user_id,
            JobTarget.deleted_at.is_(None),
        )
        .order_by(JobTarget.created_at.desc())
    )
    for target in rows:
        same_text = digest is not None and target.text_hash == digest
        same_url = url is not None and normalize_url(target.source_url) == url
        if same_text or same_url:
            return JobTargetMatch(job_target=await _job_target_out(db, target))
    return JobTargetMatch(job_target=None)


@router.get("/job-targets/{job_target_id}")
async def get_job_target(job_target_id: uuid.UUID, db: Db, me: Me) -> JobTargetOut:
    """One job target. A deleted one still answers, with deleted true and no content (R1)."""
    return await _job_target_out(db, await _owned_job_target(db, me, job_target_id))


@router.patch("/job-targets/{job_target_id}")
async def rename_job_target(
    job_target_id: uuid.UUID, body: LibraryRename, db: Db, me: Me
) -> JobTargetOut:
    """R1: rename a saved job."""
    target = await _owned_job_target(db, me, job_target_id, live=True)
    target.name = body.name
    await db.commit()
    await db.refresh(target)
    return await _job_target_out(db, target)


@router.delete("/job-targets/{job_target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job_target(job_target_id: uuid.UUID, db: Db, me: Me) -> Response:
    """R1: delete a saved job description. Its text, link, parsed data and context go.

    Gap reports, interview sessions, transcripts, debriefs and progress stay; they show the
    job as deleted. Safe to call twice.
    """
    target = await _owned_job_target(db, me, job_target_id)
    if target.deleted_at is None:
        target.deleted_at = datetime.now(UTC)
        target.name = None
        target.raw_text = None
        target.parsed_json = None
        target.source_url = None
        target.context_notes = None
        target.text_hash = None
        db.add(_audit(me, "library.job_deleted", f"job_target:{target.id}"))
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/job-targets/{job_target_id}")
async def update_job_target(
    job_target_id: uuid.UUID,
    body: JobTargetUpdate,
    db: Db,
    me: Me,
    queue: Queue,
    limits: GapLimits,
) -> JobTargetAccepted:
    """Confirm or edit the posting. A changed company name runs company matching again.

    If the job has a gap analysis and the edit changes its inputs, a new analysis starts.
    """
    target = await _owned_job_target(db, me, job_target_id, live=True)
    old_company = (target.parsed_json or {}).get("company_name")
    posting = body.posting.model_copy(update={"source_url": target.source_url})
    target.parsed_json = posting.model_dump(mode="json")
    target.level = posting.level
    target.stage = body.stage
    target.context_notes = _context_notes(body.context)
    await db.commit()

    job = None
    if posting.company_name != old_company:
        job_id = _job_id("jt", target.id)
        await queue.enqueue(
            MATCH_JOB_TARGET, job_id, job_target_id=str(target.id), org_id=str(me.org_id)
        )
        job = _job_out(await queue.info(job_id))
    await db.refresh(target)
    await gap_service.recompute(
        db, queue, org_id=me.org_id, user_id=me.user_id, settings=limits, job_target_id=target.id
    )
    await db.refresh(target)
    return JobTargetAccepted(job_target=await _job_target_out(db, target), job=job)


@router.get("/job-targets/{job_target_id}/jobs/{job_id}")
async def get_job_target_job(
    job_target_id: uuid.UUID, job_id: str, db: Db, me: Me, queue: Queue
) -> JobOut:
    await _owned_job_target(db, me, job_target_id)
    if not job_id.startswith(f"jt:{job_target_id}:"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return _job_out(await queue.info(job_id))


# --- resumes --------------------------------------------------------------------------------


@router.post("/resumes", status_code=status.HTTP_202_ACCEPTED)
async def create_resume(
    db: Db,
    me: Me,
    queue: Queue,
    file: Annotated[UploadFile | None, File()] = None,
    text: Annotated[str | None, Form(max_length=MAX_RESUME_TEXT_CHARS)] = None,
) -> ResumeAccepted:
    """Upload a PDF or DOCX file, or send pasted text in the `text` form field (IN-3)."""
    if (file is None) == (not text):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Send either a file or the resume text."
        )
    if file is not None:
        filename = PurePath(file.filename or "resume").name
        if PurePath(filename).suffix.lower() not in RESUME_EXTENSIONS:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Use a PDF, DOCX or text file."
            )
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The file is larger than 5 MB.")
        if not data:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is empty.")
    else:
        assert text is not None
        filename, data = "pasted.txt", text.encode("utf-8")

    row = ResumeRow(
        org_id=me.org_id,
        user_id=me.user_id,
        name=default_resume_name(filename if file is not None else None, datetime.now(UTC)),
        content_hash=content_hash(data),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    job_id = _job_id("rs", row.id)
    await queue.enqueue(
        PARSE_RESUME,
        job_id,
        resume_id=str(row.id),
        org_id=str(me.org_id),
        data=data,
        filename=filename,
    )
    await db.refresh(row)
    return ResumeAccepted(resume=_resume_out(row), job=_job_out(await queue.info(job_id)))


@router.get("/resumes")
async def list_resumes(db: Db, me: Me) -> list[ResumeOut]:
    """The signed-in user's saved resumes, newest first. Used to reuse a resume for a new job.

    Deleted resumes are left out (R1).
    """
    rows = await db.scalars(
        select(ResumeRow)
        .where(
            ResumeRow.org_id == me.org_id,
            ResumeRow.user_id == me.user_id,
            ResumeRow.deleted_at.is_(None),
        )
        .order_by(ResumeRow.uploaded_at.desc())
    )
    return [_resume_out(row) for row in rows]


@router.post("/resumes/match")
async def match_resume(body: ResumeMatchIn, db: Db, me: Me) -> ResumeMatch:
    """R1: the saved CV with the same file content (SHA-256 of the file, or of the pasted text
    as UTF-8). Lets the app offer the saved CV instead of reading the file again."""
    row = await db.scalar(
        select(ResumeRow)
        .where(
            ResumeRow.org_id == me.org_id,
            ResumeRow.user_id == me.user_id,
            ResumeRow.deleted_at.is_(None),
            ResumeRow.content_hash == body.sha256,
        )
        .order_by(ResumeRow.uploaded_at.desc())
        .limit(1)
    )
    return ResumeMatch(resume=_resume_out(row) if row is not None else None)


@router.get("/resumes/{resume_id}")
async def get_resume(resume_id: uuid.UUID, db: Db, me: Me) -> ResumeOut:
    """One resume. A deleted one still answers, with deleted true and no content (R1)."""
    return _resume_out(await _owned_resume(db, me, resume_id))


@router.patch("/resumes/{resume_id}")
async def rename_resume(resume_id: uuid.UUID, body: LibraryRename, db: Db, me: Me) -> ResumeOut:
    """R1: rename a saved CV."""
    row = await _owned_resume(db, me, resume_id, live=True)
    row.name = body.name
    await db.commit()
    await db.refresh(row)
    return _resume_out(row)


@router.delete("/resumes/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(resume_id: uuid.UUID, db: Db, me: Me, queue: Queue) -> Response:
    """R1: delete a saved CV: its parsed data now, its encrypted file by a worker job.

    Gap reports that used it stay and show the CV as deleted. Safe to call twice.
    """
    row = await _owned_resume(db, me, resume_id)
    if row.deleted_at is None:
        ref = row.file_ref
        row.deleted_at = datetime.now(UTC)
        row.name = None
        row.parsed_json = None
        row.file_ref = None
        row.content_hash = None
        row.confirmed_at = None
        db.add(_audit(me, "library.resume_deleted", f"resume:{row.id}"))
        await db.commit()
        if ref:
            await queue.enqueue(
                DELETE_RESUME_FILE,
                f"delete-resume:{row.id}:{uuid.uuid4().hex[:12]}",
                org_id=str(me.org_id),
                resume_id=str(row.id),
                ref=ref,
            )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/resumes/{resume_id}")
async def update_resume(
    resume_id: uuid.UUID, body: ResumeUpdate, db: Db, me: Me, queue: Queue, limits: GapLimits
) -> ResumeOut:
    """Confirm or edit the parsed resume ("Check your CV"). Gap analyses that used it start again.

    The body is validated against the Resume contract. Saving marks the CV as confirmed
    (confirmed_at), so a later re-read of the stored file does not overwrite the user's version
    without asking. Confirming is optional: a gap analysis also runs on an unconfirmed CV.
    """
    row = await _owned_resume(db, me, resume_id, live=True)
    if row.parsed_json is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The resume is still being read. Try again in a minute."
        )
    row.parsed_json = body.resume.model_dump(mode="json")
    row.confirmed_at = datetime.now(UTC)
    await db.commit()
    await gap_service.recompute(
        db, queue, org_id=me.org_id, user_id=me.user_id, settings=limits, resume_id=row.id
    )
    await db.refresh(row)
    return _resume_out(row)


@router.get("/resumes/{resume_id}/jobs/{job_id}")
async def get_resume_job(resume_id: uuid.UUID, job_id: str, db: Db, me: Me, queue: Queue) -> JobOut:
    await _owned_resume(db, me, resume_id)
    if not job_id.startswith(f"rs:{resume_id}:"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return _job_out(await queue.info(job_id))
