"""Gap analysis with the planner role (GA-1 to GA-3).

    result = await run_gap_analysis(gateway, posting, resume, profile)
    result.analysis   # GapAnalysis: match score, breakdown, strengths, gaps, probes, plan

Code decides what is rated: the requirements come from the confirmed JobPosting (ids r1, r2,
...) and the competencies come from the role family. The model only returns ratings, evidence
and text (GapAssessment). Code computes every number (see strong_worker.gap.scoring).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from strong_core.gateway import Message, ModelGateway, Role
from strong_core.profiles import ResolvedProfile
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    Competency,
    CompetencyMatch,
    CompetencyRating,
    Gap,
    GapAnalysis,
    GapAssessment,
    JobPosting,
    RequirementKind,
    RequirementMatch,
    RequirementRating,
    Resume,
    RoleFamily,
    Severity,
    Strength,
)
from strong_worker.gap import scoring
from strong_worker.gap.text import context_text, posting_text, resume_text
from strong_worker.inputs.sanitize import drop_injected_items

log = logging.getLogger(__name__)

PROMPT = "gap_analysis"
PROMPT_INPUT = "gap_analysis_input"
ATTEMPTS = 2  # the first call plus one retry
MAX_MUST_HAVE = 12
MAX_NICE_TO_HAVE = 6
MAX_STRENGTHS = 6
MAX_GAPS = 8
MAX_PROBE_AREAS = 6
MAX_PLAN = 4

_COMMON = (
    Competency.OWNERSHIP,
    Competency.IMPACT,
    Competency.COLLABORATION,
    Competency.COMMUNICATION,
    Competency.DEPTH_OF_EXPERIENCE,
    Competency.SCOPE_AT_LEVEL,
)
RATED_COMPETENCIES: dict[RoleFamily, tuple[Competency, ...]] = {
    RoleFamily.SWE: (*_COMMON, Competency.TECHNICAL_DEPTH, Competency.TRADE_OFFS),
    RoleFamily.DATA_ML: (*_COMMON, Competency.TECHNICAL_DEPTH, Competency.TRADE_OFFS),
    RoleFamily.PM: (*_COMMON, Competency.USER_AND_BUSINESS_SENSE, Competency.PRIORITIZATION),
    RoleFamily.DESIGN: (*_COMMON, Competency.USER_AND_BUSINESS_SENSE, Competency.PROBLEM_FRAMING),
    RoleFamily.TPM: (*_COMMON, Competency.TECHNICAL_DEPTH, Competency.PRIORITIZATION),
    RoleFamily.OTHER: _COMMON,
}
"""Competencies a resume can show evidence for, by role family. All are rated in every run."""


class GapAnalysisError(RuntimeError):
    pass


@dataclass(frozen=True)
class Requirement:
    id: str
    text: str
    kind: RequirementKind


@dataclass(frozen=True)
class GapResult:
    analysis: GapAnalysis
    model_version: str
    requirement_score: float | None
    competency_score: float | None
    flags: list[str] = field(default_factory=list)
    attempts: int = 1


def requirements_of(posting: JobPosting) -> list[Requirement]:
    """The requirements to rate, with stable ids. Must-haves first."""
    out: list[Requirement] = []
    seen: set[str] = set()
    groups = (
        (posting.must_have_skills[:MAX_MUST_HAVE], RequirementKind.MUST_HAVE),
        (posting.nice_to_have_skills[:MAX_NICE_TO_HAVE], RequirementKind.NICE_TO_HAVE),
    )
    for items, kind in groups:
        for text in items:
            key = text.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(Requirement(f"r{len(out) + 1}", text.strip(), kind))
    return out


def rated_competencies(posting: JobPosting) -> tuple[Competency, ...]:
    return RATED_COMPETENCIES[posting.role_family]


def build_messages(
    posting: JobPosting,
    resume: Resume,
    profile: ResolvedProfile,
    *,
    context_notes: str | None = None,
) -> list[Message]:
    reqs = requirements_of(posting)
    comps = rated_competencies(posting)
    company = (
        f"{profile.company_name} (curated profile version {profile.version})"
        if not profile.generic
        else "Generic mode: no company profile. Use a typical tech-industry bar."
    )
    level = posting.level.value if posting.level else "unknown"
    return [
        load_prompt(Role.PLANNER, PROMPT).message("system"),
        load_prompt(Role.PLANNER, PROMPT_INPUT).message(
            "user",
            company=company,
            role_family=posting.role_family.value,
            level=level,
            job=posting_text(posting),
            requirements="\n".join(f"{r.id} [{r.kind.value}] {r.text}" for r in reqs) or "(none)",
            competencies="\n".join(c.value for c in comps),
            resume=resume_text(resume),
            context=context_text(context_notes),
        ),
    ]


def assemble(
    assessment: GapAssessment,
    posting: JobPosting,
    resume: Resume,
    profile: ResolvedProfile,
) -> tuple[GapAnalysis, scoring.Scored, list[str]]:
    """Turn the model's ratings into a GapAnalysis. Pure: same inputs, same result."""
    flags: list[str] = []
    resume_words = scoring.words(resume_text(resume))

    by_id: dict[str, RequirementRating] = {}
    for item in assessment.requirements:
        by_id.setdefault(item.id.strip().lower(), item)
    req_matches: list[RequirementMatch] = []
    req_ratings: list[tuple[RequirementKind, int]] = []
    for req in requirements_of(posting):
        found = by_id.get(req.id)
        if found is None:
            flags.append(f"not_rated: {req.id}")
            rating, evidence = 0, None
        else:
            evidence = found.evidence or None
            rating = scoring.checked_rating(found.rating, evidence, resume_words)
            if rating != found.rating:
                flags.append(f"capped_without_evidence: {req.id}")
            if not scoring.evidence_in_resume(evidence, resume_words):
                evidence = None
        req_ratings.append((req.kind, rating))
        req_matches.append(
            RequirementMatch(
                requirement=req.text, kind=req.kind, score=scoring.points(rating), evidence=evidence
            )
        )

    comp_by_name: dict[Competency, CompetencyRating] = {}
    for c in assessment.competencies:
        comp_by_name.setdefault(c.competency, c)
    comp_matches: list[CompetencyMatch] = []
    comp_ratings: list[tuple[Competency, int]] = []
    for comp in rated_competencies(posting):
        rated = comp_by_name.get(comp)
        if rated is None:
            flags.append(f"not_rated: {comp.value}")
        rating = rated.rating if rated else 0
        comp_ratings.append((comp, rating))
        comp_matches.append(
            CompetencyMatch(
                competency=comp,
                score=scoring.points(rating),
                notes=(rated.notes if rated and rated.notes else None),
            )
        )

    scored = scoring.match_score(req_ratings, comp_ratings, profile.scoring_weights)

    strengths: list[Strength] = []
    for s in assessment.strengths:
        if scoring.evidence_in_resume(s.evidence, resume_words):
            strengths.append(s)
        else:
            flags.append(f"strength_without_resume_evidence: {s.summary[:80]}")
    strengths = _dedupe(strengths, lambda s: s.summary)[:MAX_STRENGTHS]

    gaps = list(assessment.gaps)
    named = {(g.related_requirement or "").strip().lower() for g in gaps}
    for match, (kind, rating) in zip(req_matches, req_ratings, strict=True):
        if kind != RequirementKind.MUST_HAVE or rating > 1:
            continue
        if match.requirement.lower() in named:
            continue
        gaps.append(
            Gap(
                summary=f"Little or no resume evidence for: {match.requirement}",
                severity=Severity.HIGH if rating == 0 else Severity.MEDIUM,
                related_requirement=match.requirement,
            )
        )
    severity_rank = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}
    gaps = sorted(_dedupe(gaps, lambda g: g.summary), key=lambda g: severity_rank[g.severity])

    probes, dropped = drop_injected_items(_dedupe(assessment.probe_areas, lambda p: p))
    flags += [f"dropped_from_output: {d[:80]}" for d in dropped]

    plan = [
        p.model_copy(update={"priority": i})
        for i, p in enumerate(sorted(assessment.session_plan, key=lambda p: p.priority), start=1)
    ][:MAX_PLAN]

    analysis = GapAnalysis(
        match_score=scored.match_score,
        requirement_breakdown=req_matches,
        competency_breakdown=comp_matches,
        strengths=strengths,
        gaps=gaps[:MAX_GAPS],
        probe_areas=probes[:MAX_PROBE_AREAS],
        session_plan=plan,
    )
    return analysis, scored, flags


async def run_gap_analysis(
    gateway: ModelGateway,
    posting: JobPosting,
    resume: Resume,
    profile: ResolvedProfile,
    *,
    context_notes: str | None = None,
) -> GapResult:
    """Ask the planner for ratings, then build the GapAnalysis in code. Retries once."""
    messages = build_messages(posting, resume, profile, context_notes=context_notes)
    errors: list[str] = []
    for attempt in range(1, ATTEMPTS + 1):
        try:
            done = await gateway.complete(Role.PLANNER, messages, output_type=GapAssessment)
        except Exception as exc:  # gateway, network or validation error: retry once
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}"[:300])
            log.warning("planner gap call failed (%s), attempt %d", type(exc).__name__, attempt)
            continue
        analysis, scored, flags = assemble(done.output, posting, resume, profile)
        version = f"{done.model} {' '.join(done.prompt_refs)}".strip()[:200]
        return GapResult(
            analysis,
            version,
            scored.requirement_score,
            scored.competency_score,
            flags,
            attempt,
        )
    raise GapAnalysisError(f"Gap analysis failed after {ATTEMPTS} attempts: " + " | ".join(errors))


def _dedupe[T](items: Sequence[T], key: Callable[[T], str]) -> list[T]:
    seen: set[str] = set()
    out: list[T] = []
    for item in items:
        k = key(item).strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(item)
    return out


__all__ = [
    "RATED_COMPETENCIES",
    "GapAnalysisError",
    "GapResult",
    "Requirement",
    "assemble",
    "build_messages",
    "rated_competencies",
    "requirements_of",
    "run_gap_analysis",
]
