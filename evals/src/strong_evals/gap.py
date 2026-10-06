"""Gap analysis and the real planner (P6) in the eval harness.

- GapPlanner is the real planner behind the `Planner` interface: it runs the gap analysis for
  the persona's resume and a matching posting fixture, then builds the interviewer brief with
  strong_worker.gap. Simulated sessions use it by default (it replaced StubPlanner).
- run_gap_item runs one gap analysis (posting fixture + resume fixture) several times and keeps
  each match score, so the report can show the spread across runs (GA-1 asks for 3 points or
  less) and whether matched pairs score above mismatched pairs.

The postings and resumes are the P2 fixtures in evals/fixtures/inputs.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from strong_core.gateway import ModelGateway
from strong_core.profiles import ResolvedProfile, generic_profile
from strong_core.schemas import (
    CompanyProfile,
    InterviewerBrief,
    JobPosting,
    Resume,
    SessionConfig,
)
from strong_evals import EVALS_DIR
from strong_evals.candidate import Persona
from strong_evals.suites import GapSpec
from strong_worker.gap.analysis import run_gap_analysis
from strong_worker.gap.brief import build_brief

INPUTS_DIR = EVALS_DIR / "fixtures" / "inputs"
PROFILES_DIR = EVALS_DIR.parent / "profiles"

# The posting each resume fixture is meant for. Used by GapPlanner for simulated sessions.
POSTING_FOR_RESUME = {
    "backend-senior": "swe-stripe-backend",
    "ml-engineer-staff": "data-databricks-ml-serving",
    "new-grad-swe": "swe-northwind-newgrad",
    "product-designer-senior": "design-airbnb-product-designer",
    "product-manager-mid": "pm-shopify-checkout",
    "tpm-career-changer": "tpm-harbor-robotics",
}


def load_posting(name: str, folder: Path = INPUTS_DIR) -> JobPosting:
    return JobPosting.model_validate_json(
        (folder / "postings" / f"{name}.json").read_text(encoding="utf-8")
    )


def load_resume(name: str, folder: Path = INPUTS_DIR) -> Resume:
    return Resume.model_validate_json(
        (folder / "resumes" / f"{name}.json").read_text(encoding="utf-8")
    )


def load_profile(path: str | None) -> ResolvedProfile:
    """A profile file under profiles/ in company mode, else generic mode.

    The harness has no database, so the version comes from the file's meta.version.
    """
    if not path:
        return generic_profile()
    profile = CompanyProfile.model_validate_json((PROFILES_DIR / path).read_text(encoding="utf-8"))
    company_id = uuid.uuid5(uuid.NAMESPACE_URL, f"strong-hire-evals/{profile.company_slug}")
    return ResolvedProfile.from_profile(
        profile, company_id=company_id, version=profile.meta.version
    )


class GapPlanner:
    """The real planner for simulated sessions: gap analysis, then the interviewer brief."""

    def __init__(self, gateway: ModelGateway, profile: ResolvedProfile | None = None) -> None:
        self.gateway = gateway
        self.profile = profile or generic_profile()

    async def brief(self, config: SessionConfig, persona: Persona) -> InterviewerBrief:
        posting = load_posting(POSTING_FOR_RESUME.get(persona.resume_id, "swe-stripe-backend"))
        gap = await run_gap_analysis(self.gateway, posting, persona.resume, self.profile)
        built = await build_brief(
            self.gateway, config, posting, persona.resume, self.profile, gap=gap.analysis
        )
        return built.brief


@dataclass
class GapResult:
    spec: GapSpec
    scores: list[int] = field(default_factory=list)
    requirement_scores: list[float | None] = field(default_factory=list)
    seconds: list[float] = field(default_factory=list)
    generic_mode: bool = True
    cost_usd: Decimal = Decimal(0)
    error: str | None = None

    @property
    def spread(self) -> int | None:
        return max(self.scores) - min(self.scores) if len(self.scores) > 1 else None

    @property
    def mean(self) -> float | None:
        return sum(self.scores) / len(self.scores) if self.scores else None


async def run_gap_item(spec: GapSpec, gateway: ModelGateway) -> GapResult:
    profile = load_profile(spec.profile)
    result = GapResult(spec, generic_mode=profile.generic)
    try:
        posting, resume = load_posting(spec.posting), load_resume(spec.resume)
        for _ in range(spec.runs):
            started = time.perf_counter()
            done = await run_gap_analysis(gateway, posting, resume, profile)
            result.seconds.append(round(time.perf_counter() - started, 2))
            result.scores.append(done.analysis.match_score)
            result.requirement_scores.append(done.requirement_score)
    except Exception as e:  # a model that fails validation counts as an error, not a crash
        result.error = f"{type(e).__name__}: {e}"[:300]
    return result


def fit_order(results: list[GapResult]) -> tuple[int, int]:
    """(passed, checked): for each posting, does every matched pair score above every
    mismatched pair?"""
    passed = checked = 0
    by_posting: dict[str, list[GapResult]] = {}
    for r in results:
        if r.mean is not None:
            by_posting.setdefault(r.spec.posting, []).append(r)
    for items in by_posting.values():
        matched = [r.mean for r in items if r.spec.fit == "match" and r.mean is not None]
        other = [r.mean for r in items if r.spec.fit == "mismatch" and r.mean is not None]
        for m in matched:
            for o in other:
                checked += 1
                passed += m > o
    return passed, checked
