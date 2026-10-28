"""Approved auto-profiles in the interviewer brief (AP-2)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.config import get_settings
from strong_core.db.models import CompanyAutoProfile, InterviewSession, JobTarget
from strong_core.db.models import GapAnalysis as GapRow
from strong_core.db.models import Resume as ResumeRow
from strong_core.gateway import ModelGateway
from strong_core.profiles import ResolvedProfile, generic_profile
from strong_core.schemas import (
    AutoProfileStatus,
    BriefDraft,
    CompanyProfile,
    Difficulty,
    GapStatus,
    InterviewerBrief,
    InterviewType,
    JobPosting,
    Level,
    Mode,
    SessionConfig,
)
from strong_core.schemas.session import BRIEF_COMPANY_SUMMARY_MAX
from strong_worker.gap import jobs as gap_jobs
from strong_worker.gap.brief import (
    AUTO_SUMMARY_LABEL,
    MAX_BRIEF_TOKENS,
    assemble,
    brief_tokens,
    company_summary,
)
from strong_worker.gap.jobs import CTX_KEY, GapContext

ROOT = get_settings().repo_root
INPUTS = ROOT / "evals/fixtures/inputs"
DRAFT = ROOT / "packages/core/src/strong_core/gateway/fixtures/planner/BriefDraft.json"
POSTING = JobPosting.model_validate_json(
    (INPUTS / "postings/swe-stripe-backend.json").read_text(encoding="utf-8")
)
SUMMARY = "Stripe builds payment infrastructure. Small teams own their services end to end."
Account = tuple[uuid.UUID, uuid.UUID]


def config() -> SessionConfig:
    return SessionConfig(
        interview_type=InterviewType.BEHAVIORAL,
        difficulty=Difficulty.REALISTIC,
        mode=Mode.REALISTIC,
        duration_min=30,
        level=Level.SENIOR,
    )


def draft() -> BriefDraft:
    return BriefDraft.model_validate_json(DRAFT.read_text(encoding="utf-8"))


def company() -> ResolvedProfile:
    profile = CompanyProfile.model_validate_json(
        (ROOT / "profiles/examples/example-corp.json").read_text(encoding="utf-8")
    )
    return ResolvedProfile.from_profile(profile, company_id=uuid.uuid4(), version=3)


def _json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def test_ap2_summary_is_labeled_auto_generated_and_changes_nothing_else() -> None:
    """AP-2: in generic mode the summary is added, labeled; competencies, values, questions,
    persona and every other field are the same as without it, so weights are untouched."""
    without, _ = assemble(draft(), config(), POSTING, generic_profile(), None)
    with_summary, flags = assemble(
        draft(), config(), POSTING, generic_profile(), None, auto_summary=SUMMARY
    )

    assert with_summary.company_summary == AUTO_SUMMARY_LABEL + SUMMARY
    assert "auto-generated" in with_summary.company_summary.lower()
    assert without.company_summary is None
    assert with_summary.model_dump(exclude={"company_summary"}) == without.model_dump(
        exclude={"company_summary"}
    )
    assert "dropped_company_summary" not in flags


def test_ap2_curated_profiles_never_carry_an_auto_summary() -> None:
    """AP-2: a curated company's brief ignores any auto-profile summary."""
    brief, _ = assemble(draft(), config(), POSTING, company(), None, auto_summary=SUMMARY)
    assert brief.company_summary is None
    assert company_summary(company(), SUMMARY) is None


def test_ap2_summary_is_capped_and_blank_is_ignored() -> None:
    assert company_summary(generic_profile(), "   ") is None
    long = company_summary(generic_profile(), "word " * 1000)
    assert long is not None and len(long) == BRIEF_COMPANY_SUMMARY_MAX


def test_ap2_summary_is_dropped_before_the_brief_goes_over_its_token_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AP-2: the summary must not cost the interviewer its questions or a fast live loop."""
    base, _ = assemble(draft(), config(), POSTING, generic_profile(), None)
    monkeypatch.setattr("strong_worker.gap.brief.MAX_BRIEF_TOKENS", brief_tokens(base) + 5)
    brief, flags = assemble(
        draft(), config(), POSTING, generic_profile(), None, auto_summary=SUMMARY * 4
    )
    assert brief.company_summary is None
    assert "dropped_company_summary" in flags
    assert brief.model_dump() == base.model_dump()
    assert MAX_BRIEF_TOKENS == 1500  # the patch above is local to this test


async def _auto_profile(maker: async_sessionmaker[AsyncSession], status: AutoProfileStatus) -> None:
    async with maker() as db:
        db.add(
            CompanyAutoProfile(
                company_name="Stripe",
                normalized_name="stripe",
                source_host="stripe.com",
                summary=SUMMARY,
                summary_json={"summary": SUMMARY, "sources": ["https://stripe.com/jobs"]},
                sources_json=["https://stripe.com/jobs"],
                status=status,
                model_profile="fake",
                model_id="fake-extractor",
                prompt_version="extractor/auto_profile.v1",
            )
        )
        await db.commit()


async def _brief_for_generic_session(
    maker: async_sessionmaker[AsyncSession], account: Account, gateway: ModelGateway
) -> InterviewerBrief:
    org_id, user_id = account
    async with maker() as db:
        target = JobTarget(  # no company_id: generic mode
            org_id=org_id,
            user_id=user_id,
            parsed_json=_json(INPUTS / "postings/swe-stripe-backend.json"),
        )
        resume = ResumeRow(
            org_id=org_id,
            user_id=user_id,
            parsed_json=_json(INPUTS / "resumes/backend-senior.json"),
        )
        db.add_all([target, resume])
        await db.flush()
        gap = GapRow(
            org_id=org_id, job_target_id=target.id, resume_id=resume.id, status=GapStatus.RUNNING
        )
        db.add(gap)
        await db.commit()
        target_id, gap_id = target.id, gap.id
    ctx: dict[str, Any] = {CTX_KEY: GapContext(sessionmaker=maker, gateway=gateway)}
    await gap_jobs.run_gap_analysis_job(ctx, str(gap_id), str(org_id))
    async with maker() as db:
        session = InterviewSession(
            org_id=org_id,
            job_target_id=target_id,
            type=InterviewType.BEHAVIORAL,
            difficulty=Difficulty.REALISTIC,
            mode=Mode.REALISTIC,
            duration_min=30,
        )
        db.add(session)
        await db.commit()
        session_id = session.id
    result = await gap_jobs.build_interviewer_brief(ctx, str(session_id), str(org_id))
    assert result["outcome"] == "ready", result
    async with maker() as db:
        stored = await db.get(InterviewSession, session_id)
        assert stored is not None and stored.brief_json is not None
        return InterviewerBrief.model_validate(stored.brief_json)


async def test_ap2_brief_job_adds_an_approved_auto_profile(
    sessionmaker: async_sessionmaker[AsyncSession], account: Account, gateway: ModelGateway
) -> None:
    """AP-2: the brief job reads the approved auto-profile when it builds a generic brief."""
    await _auto_profile(sessionmaker, AutoProfileStatus.APPROVED)
    brief = await _brief_for_generic_session(sessionmaker, account, gateway)
    assert brief.generic_mode
    assert brief.company_summary == AUTO_SUMMARY_LABEL + SUMMARY


@pytest.mark.parametrize("status", [AutoProfileStatus.PENDING, AutoProfileStatus.RETIRED])
async def test_ap2_brief_job_ignores_unapproved_auto_profiles(
    sessionmaker: async_sessionmaker[AsyncSession],
    account: Account,
    gateway: ModelGateway,
    status: AutoProfileStatus,
) -> None:
    """AP-2, AP-3: a pending or retired auto-profile never reaches a brief."""
    await _auto_profile(sessionmaker, status)
    brief = await _brief_for_generic_session(sessionmaker, account, gateway)
    assert brief.company_summary is None


def test_ap2_live_loop_never_reads_auto_profiles() -> None:
    """AP-2: no interview latency. Only the brief job (before the session) reads auto-profiles;
    the voice agent reads the stored brief and nothing else."""
    voice = Path(__file__).parents[2] / "voice" / "src"
    for path in voice.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "CompanyAutoProfile" not in text and "auto_profile" not in text, path
