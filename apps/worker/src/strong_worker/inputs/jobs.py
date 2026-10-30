"""Arq jobs for job and resume inputs. The API creates the rows and enqueues these jobs.

Each job returns a JSON-safe dict that the API shows through its status endpoint:

    {"outcome": "extracted" | "needs_paste" | "rejected" | "failed", ...details}

"rejected" means the input is not a job description (IN-6) or not a CV (IN-7); its "reason" is
a message for the user. A refused CV file is not stored.

Jobs return a failure outcome instead of raising, so users see a plain reason.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from arq import Retry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db import get_sessionmaker
from strong_core.db.models import JobTarget
from strong_core.db.models import Resume as ResumeRow
from strong_core.gateway import ModelGateway, get_gateway
from strong_core.library import default_job_name, posting_text_hash
from strong_core.schemas import JobPosting
from strong_core.sim import gateway_for_org
from strong_worker.inputs.check import check_input
from strong_worker.inputs.documents import KIND_EXTENSIONS, DocumentError, document_text
from strong_worker.inputs.extract import (
    MIN_POSTING_CHARS,
    MIN_RESUME_CHARS,
    ExtractionError,
    extract_job_posting,
    extract_resume,
)
from strong_worker.inputs.fetch import PostingFetcher, playwright_render
from strong_worker.inputs.matching import match_and_log
from strong_worker.inputs.sanitize import sanitize_untrusted
from strong_worker.inputs.settings import get_inputs_settings
from strong_worker.inputs.storage import FileStore, build_file_store
from strong_worker.inputs.story_ideas import queue_story_idea_skills, story_idea_skills
from strong_worker.ops.context import job_context
from strong_worker.profiles.queue import queue_auto_profile

log = logging.getLogger(__name__)

CTX_KEY = "inputs"
RESULT_TTL_S = 24 * 3600

# IN-1: must match strong_api.inputs.limits (a test checks this). The worker cannot import it.
MAX_POSTING_WORDS = 2_500
POSTING_TOO_LONG_MESSAGE = (
    "Job descriptions can be up to 2,500 words. Trim the benefits and company boilerplate."
)


@dataclass
class InputsContext:
    sessionmaker: async_sessionmaker[AsyncSession]
    gateway: ModelGateway
    store: FileStore
    fetcher: PostingFetcher


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_inputs_settings()
    http = httpx.AsyncClient(timeout=settings.inputs_fetch_timeout_s)
    ctx["inputs_http"] = http
    ctx[CTX_KEY] = InputsContext(
        sessionmaker=get_sessionmaker(),
        gateway=get_gateway(),
        store=build_file_store(settings),
        fetcher=PostingFetcher(
            http, renderer=playwright_render if settings.inputs_browser_fallback else None
        ),
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    http = ctx.pop("inputs_http", None)
    if http is not None:
        await http.aclose()


def _inputs(ctx: dict[str, Any]) -> InputsContext:
    inputs = ctx[CTX_KEY]
    assert isinstance(inputs, InputsContext)
    return inputs


def _failed(reason: str) -> dict[str, Any]:
    return {"outcome": "failed", "reason": reason}


@job_context()
async def extract_job_target(
    ctx: dict[str, Any], job_target_id: str, org_id: str
) -> dict[str, Any]:
    """Fetch the posting if only a URL was given, extract a JobPosting, then match the company."""
    inputs = _inputs(ctx)
    async with inputs.sessionmaker() as db:
        target = await _job_target(db, job_target_id, org_id)
        if target is None or target.deleted_at is not None:
            return _failed("job target not found")

        board = None
        fetched_now = False
        if not target.raw_text:
            if not target.source_url:
                return _failed("The job target has no text and no URL.")
            fetched = await inputs.fetcher.fetch(target.source_url)
            if fetched.needs_paste:
                return {
                    "outcome": "needs_paste",
                    "reason": fetched.paste_reason,
                    "detail": fetched.detail,
                }
            if len((fetched.text or "").split()) > MAX_POSTING_WORDS:
                return {
                    "outcome": "needs_paste",
                    "reason": "too_long",
                    "detail": POSTING_TOO_LONG_MESSAGE,
                }
            target.raw_text = fetched.text
            target.text_hash = posting_text_hash(fetched.text)
            board = fetched.board
            fetched_now = True
            await db.commit()

        assert target.raw_text is not None
        try:
            gateway = await gateway_for_org(db, target.org_id, inputs.gateway)  # P13
            if _long_enough(target.raw_text, MIN_POSTING_CHARS):  # else the extraction says why
                refusal = await check_input(
                    gateway, target.raw_text, "job_posting", "link" if fetched_now else "text"
                )
                if refusal is not None:  # IN-6
                    return refusal.result()
            extraction = await extract_job_posting(
                gateway, target.raw_text, source_url=target.source_url
            )
        except ExtractionError as exc:
            return _failed(str(exc))

        posting = extraction.output
        match = await match_and_log(
            db,
            org_id=target.org_id,
            user_id=target.user_id,
            job_target_id=target.id,
            company_name=posting.company_name,
            source_url=target.source_url,
        )
        target.parsed_json = posting.model_dump(mode="json")
        target.level = posting.level
        target.company_id = match.company.id if match.company else None
        if target.name is None:  # R1: the default library name; a rename is kept
            target.name = default_job_name(target.parsed_json, target.source_url, target.created_at)
        await db.commit()
        if match.generic_mode:  # AP-1
            await queue_auto_profile(
                ctx, company_name=posting.company_name, source_url=target.source_url, org_id=org_id
            )
        return {
            "outcome": "extracted",
            "board": board,
            "company": match.summary(),
            **extraction.summary(),
        }


@job_context()
async def match_job_target(ctx: dict[str, Any], job_target_id: str, org_id: str) -> dict[str, Any]:
    """Match again after the user edits the company name (IN-5)."""
    inputs = _inputs(ctx)
    async with inputs.sessionmaker() as db:
        target = await _job_target(db, job_target_id, org_id)
        if target is None or target.parsed_json is None or target.deleted_at is not None:
            return _failed("job target not found or not extracted")
        posting = JobPosting.model_validate(target.parsed_json)
        match = await match_and_log(
            db,
            org_id=target.org_id,
            user_id=target.user_id,
            job_target_id=target.id,
            company_name=posting.company_name,
            source_url=target.source_url,
        )
        target.company_id = match.company.id if match.company else None
        await db.commit()
        if match.generic_mode:  # AP-1
            await queue_auto_profile(
                ctx, company_name=posting.company_name, source_url=target.source_url, org_id=org_id
            )
        return {"outcome": "matched", "company": match.summary()}


@job_context()
async def parse_resume(
    ctx: dict[str, Any],
    resume_id: str,
    org_id: str,
    data: bytes,
    filename: str | None = None,
) -> dict[str, Any]:
    """Store the original file encrypted, read its text, and extract a Resume (IN-3)."""
    inputs = _inputs(ctx)
    async with inputs.sessionmaker() as db:
        row = await db.scalar(
            select(ResumeRow).where(
                ResumeRow.id == uuid.UUID(resume_id), ResumeRow.org_id == uuid.UUID(org_id)
            )
        )
        if row is None or row.deleted_at is not None:
            return _failed("resume not found")
        try:
            kind, text = document_text(data, filename)
        except DocumentError as exc:
            return _failed(str(exc))

        if _long_enough(text, MIN_RESUME_CHARS):  # else the extraction says why
            gateway = await gateway_for_org(db, row.org_id, inputs.gateway)  # P13
            refusal = await check_input(
                gateway, text, "resume", "text" if kind == "text" else "file"
            )
            if refusal is not None:  # IN-7: the file is not stored
                return refusal.result()

        key = f"resumes/{row.org_id}/{row.id}.{KIND_EXTENSIONS[kind]}"
        ref = await inputs.store.put(key, data)
        row.file_ref = ref
        await db.commit()
        await db.refresh(row)
        if row.deleted_at is not None:  # R1: deleted before the file was saved; keep nothing
            await inputs.store.delete(ref)
            row.file_ref = None
            await db.commit()
            return _failed("resume deleted")

        try:
            gateway = await gateway_for_org(db, row.org_id, inputs.gateway)  # P13
            extraction = await extract_resume(gateway, text)
        except ExtractionError as exc:
            return _failed(str(exc))
        await db.refresh(row)
        if row.deleted_at is not None:  # deleted while it was read; the API removes the file
            return _failed("resume deleted")
        row.parsed_json = extraction.output.model_dump(mode="json")
        await db.commit()
    # RM-4: the likely skills of the resume's story ideas, after the session is closed.
    await queue_story_idea_skills(ctx, resume_id, org_id)
    return {"outcome": "extracted", "kind": kind, **extraction.summary()}


DELETE_FILE_MAX_TRIES = 10
DELETE_RETRY_DELAY_S = 600


async def delete_resume_file(
    ctx: dict[str, Any], org_id: str, resume_id: str, ref: str
) -> dict[str, Any]:
    """R1: delete the encrypted original file of a deleted CV. Retried on storage errors."""
    inputs = _inputs(ctx)
    try:
        await inputs.store.delete(ref)  # a missing file is not an error
    except Exception as exc:
        job_try = int(ctx.get("job_try", 1))
        log.warning("file delete for resume %s failed (try %d): %s", resume_id, job_try, exc)
        if job_try < DELETE_FILE_MAX_TRIES:
            raise Retry(defer=DELETE_RETRY_DELAY_S * job_try) from exc
        raise
    return {"outcome": "deleted", "resume_id": resume_id, "org_id": org_id}


def _long_enough(text: str, minimum: int) -> bool:
    return len(sanitize_untrusted(text).text) >= minimum


async def _job_target(db: AsyncSession, job_target_id: str, org_id: str) -> JobTarget | None:
    return await db.scalar(
        select(JobTarget).where(
            JobTarget.id == uuid.UUID(job_target_id), JobTarget.org_id == uuid.UUID(org_id)
        )
    )


FUNCTIONS = (
    extract_job_target,
    match_job_target,
    parse_resume,
    delete_resume_file,
    story_idea_skills,
)
