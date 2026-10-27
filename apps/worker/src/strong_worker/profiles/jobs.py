"""Arq job that builds an auto-profile for a company outside the curated list (AP-1).

The input jobs queue it when a job target lands in generic mode. It runs once per company:
when a pending or approved auto-profile exists for the normalized company name, the job reuses
it and fetches nothing. Otherwise it reads a few careers and values pages on the posting's
domain, runs the extractor with the auto_profile prompt, and stores the result as `pending`.
An admin approves it before any brief uses it (AP-3); see `approved_auto_profile`.

Page text is untrusted: the injection filter runs on every page before the prompt sees it, the
pages sit in the user message inside a data block, and list items that still look like
instructions are dropped from the output.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.config import get_settings
from strong_core.db.models import CompanyAutoProfile
from strong_core.gateway import Message, ModelGateway, Role
from strong_core.prompts import load_prompt
from strong_core.schemas import AutoProfileStatus, AutoProfileSummary
from strong_worker.inputs.jobs import CTX_KEY, InputsContext
from strong_worker.inputs.sanitize import drop_injected_items, sanitize_untrusted
from strong_worker.ops.context import job_context
from strong_worker.profiles.pages import Page, fetch_company_pages, pages_block
from strong_worker.profiles.queue import usable_name

log = logging.getLogger(__name__)

RESULT_TTL_S = 24 * 3600
ATTEMPTS = 2  # the first call plus one retry


def _inputs(ctx: dict[str, Any]) -> InputsContext:
    inputs = ctx[CTX_KEY]
    assert isinstance(inputs, InputsContext)
    return inputs


async def live_auto_profile(db: AsyncSession, normalized_name: str) -> CompanyAutoProfile | None:
    """The pending or approved auto-profile for a company, if any."""
    return await db.scalar(
        select(CompanyAutoProfile).where(
            CompanyAutoProfile.normalized_name == normalized_name,
            CompanyAutoProfile.status != AutoProfileStatus.RETIRED,
        )
    )


async def approved_auto_profile(
    db: AsyncSession, company_name: str | None
) -> CompanyAutoProfile | None:
    """AP-2: the auto-profile a brief may use. Only an admin-approved row counts."""
    normalized = usable_name(company_name)
    if normalized is None:
        return None
    row = await live_auto_profile(db, normalized)
    return row if row is not None and row.status == AutoProfileStatus.APPROVED else None


def build_auto_profile_messages(company_name: str, pages: list[Page]) -> list[Message]:
    company = sanitize_untrusted(company_name, max_chars=200).text
    return [
        load_prompt(Role.EXTRACTOR, "auto_profile").message("system"),
        load_prompt(Role.EXTRACTOR, "auto_profile_input").message(
            "user", company=company, pages=pages_block(pages)
        ),
    ]


def clean_summary(
    summary: AutoProfileSummary, pages: list[Page]
) -> tuple[AutoProfileSummary, list[str]]:
    """Drop output that still looks like instructions, and keep only URLs we really fetched."""
    dropped: list[str] = []
    values, gone = drop_injected_items(summary.values_mentioned)
    dropped += gone
    notes, gone = drop_injected_items(summary.interview_process_notes)
    dropped += gone
    fetched = [p.url for p in pages]
    sources = [u for u in summary.sources if u in fetched] or fetched
    text = summary.summary
    if drop_injected_items([text])[1]:
        raise ValueError("the summary looks like instructions to a model")
    cleaned = summary.model_copy(
        update={"values_mentioned": values, "interview_process_notes": notes, "sources": sources}
    )
    return cleaned, [f"dropped_from_output: {d[:120]}" for d in dropped]


async def summarize(
    gateway: ModelGateway, company_name: str, pages: list[Page]
) -> tuple[AutoProfileSummary, str, tuple[str, ...], list[str]]:
    messages = build_auto_profile_messages(company_name, pages)
    errors: list[str] = []
    for attempt in range(1, ATTEMPTS + 1):
        try:
            done = await gateway.complete(Role.EXTRACTOR, messages, output_type=AutoProfileSummary)
            summary, flags = clean_summary(done.output, pages)
        except Exception as exc:  # gateway, validation or injected output: retry once
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}"[:300])
            log.warning("auto-profile call failed (%s), attempt %d", type(exc).__name__, attempt)
            continue
        return summary, done.model, done.prompt_refs, flags
    raise RuntimeError("auto-profile extraction failed: " + " | ".join(errors))


@job_context()
async def build_auto_profile(
    ctx: dict[str, Any], company_name: str, source_url: str, org_id: str | None = None
) -> dict[str, Any]:
    """AP-1: build or reuse the auto-profile for one company. Never raises."""
    normalized = usable_name(company_name)
    if normalized is None:
        return {"outcome": "skipped", "reason": "no usable company name"}
    inputs = _inputs(ctx)
    async with inputs.sessionmaker() as db:
        existing = await live_auto_profile(db, normalized)
        if existing is not None:
            return {"outcome": "reused", "auto_profile_id": str(existing.id)}

        found = await fetch_company_pages(inputs.fetcher, source_url)
        if found.host is None:
            return {"outcome": "skipped", "reason": "the posting is not on the company's domain"}
        if not found.pages:
            return {"outcome": "skipped", "reason": f"no readable pages on {found.host}"}

        try:
            summary, model, refs, flags = await summarize(inputs.gateway, company_name, found.pages)
        except RuntimeError as exc:
            return {"outcome": "failed", "reason": str(exc)}

        row = CompanyAutoProfile(
            company_name=company_name[:200],
            normalized_name=normalized[:200],
            source_host=found.host,
            summary=summary.summary,
            summary_json=summary.model_dump(mode="json"),
            sources_json=found.urls,
            status=AutoProfileStatus.PENDING,
            model_profile=str(get_settings().model_profile),
            model_id=model,
            prompt_version=",".join(refs),
        )
        db.add(row)
        try:
            await db.commit()
        except IntegrityError:  # another job stored this company first
            await db.rollback()
            existing = await live_auto_profile(db, normalized)
            return {"outcome": "reused", "auto_profile_id": str(existing.id) if existing else None}
        return {
            "outcome": "created",
            "auto_profile_id": str(row.id),
            "sources": found.urls,
            "flags": found.flags + flags,
            "model": model,
            "prompt_refs": list(refs),
        }


FUNCTIONS = (build_auto_profile,)
