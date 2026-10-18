"""CU-2: suggested focus chips per question category. Rules in code, no model call.

Sources, best first, for each category:
1. the focus topics of the gap analysis session plan for that type (by plan priority);
2. behavioral, technical Q&A and hiring manager: the gap analysis probe areas;
3. technical Q&A and hiring manager: the requirement behind each gap (high severity first), then
   the job posting's must-have skills;
4. every category: its competencies the gap analysis rated weakest (score under 60), as labels
   like "Conflict handling".

Chips are cleaned (single spaces, no trailing punctuation), at most 60 characters (longer ones
are dropped, not cut), deduplicated without regard to case, and at most 8 per category. Text that
looks like instructions to the interviewer is dropped: postings are untrusted text. The first 3
chips are pre-selected.
"""

from __future__ import annotations

from collections.abc import Iterable

from strong_api.custom.check import clean_text, looks_like_instructions
from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    STANDARD_INTERVIEW_TYPES,
    GapAnalysis,
    InterviewType,
    JobPosting,
)
from strong_core.schemas.custom import CUSTOM_FOCUS_MAX_LEN, CUSTOM_MAX_FOCUS
from strong_core.schemas.enums import Severity

PRESELECTED = 3
WEAK_BELOW = 60
_SEVERITY_RANK = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}
_WITH_PROBES = {InterviewType.BEHAVIORAL, InterviewType.TECHNICAL_QA, InterviewType.HIRING_MANAGER}
_WITH_SKILLS = {InterviewType.TECHNICAL_QA, InterviewType.HIRING_MANAGER}


def chip(text: str) -> str | None:
    """The cleaned chip, or None when it is empty, too long or looks like instructions."""
    value = clean_text(text).strip(" .;:,-")
    if not value or len(value) > CUSTOM_FOCUS_MAX_LEN or looks_like_instructions(value):
        return None
    return value


def _dedupe(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = chip(raw)
        if value is None or value.casefold() in seen:
            continue
        seen.add(value.casefold())
        out.append(value)
        if len(out) == CUSTOM_MAX_FOCUS:
            break
    return out


def suggest_focus(
    posting: JobPosting | None, gap: GapAnalysis | None
) -> dict[InterviewType, tuple[list[str], list[str]]]:
    """(suggested, preselected) chips for each of the four standard types."""
    out: dict[InterviewType, tuple[list[str], list[str]]] = {}
    must_haves = posting.must_have_skills if posting is not None else []
    for itype in STANDARD_INTERVIEW_TYPES:
        values: list[str] = []
        if gap is not None:
            for planned in sorted(gap.session_plan, key=lambda p: p.priority):
                if planned.interview_type == itype:
                    values += planned.focus_topics
            if itype in _WITH_PROBES:
                values += gap.probe_areas
            if itype in _WITH_SKILLS:
                gaps = sorted(gap.gaps, key=lambda g: _SEVERITY_RANK.get(g.severity, 3))
                values += [g.related_requirement for g in gaps if g.related_requirement]
        if itype in _WITH_SKILLS:
            values += must_haves
        if gap is not None:
            comps = COMPETENCIES_BY_TYPE[itype]
            weak = sorted(
                (c for c in gap.competency_breakdown if c.competency in comps),
                key=lambda c: (c.score, c.competency.value),
            )
            values += [
                c.competency.value.replace("_", " ").capitalize()
                for c in weak
                if c.score < WEAK_BELOW
            ]
        suggested = _dedupe(values)
        out[itype] = (suggested, suggested[:PRESELECTED])
    return out
