"""Field-level confidence for extracted postings and resumes.

The check is grounding, not model self-report: a field is high confidence when its value can be
found in the source text, medium when it is partly found or inferred, and low when it is empty or
not found. The UI uses this to ask the user to check low-confidence fields first (IN-2).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from strong_core.schemas import Confidence, JobPosting, Resume, RoleFamily

_NON_WORD = re.compile(r"[^a-z0-9+#]+")

FAMILY_KEYWORDS: dict[RoleFamily, tuple[str, ...]] = {
    RoleFamily.SWE: ("engineer", "developer", "software", "sre", "reliability", "security"),
    RoleFamily.DATA_ML: ("data", "machine learning", "ml", "scientist", "analytics", "ai"),
    RoleFamily.PM: ("product manager", "product lead", "product owner"),
    RoleFamily.DESIGN: ("designer", "design", "ux", "researcher"),
    RoleFamily.TPM: ("program manager", "tpm"),
}


def normalize(text: str) -> str:
    return " " + _NON_WORD.sub(" ", text.lower()).strip() + " "


def grounding(value: str, source: str) -> float:
    """1.0 when the normalized value appears in the normalized source, else the share of its
    words found there. `source` must already be normalized."""
    needle = normalize(value)
    if needle.strip() and needle in source:
        return 1.0
    words = [w for w in needle.split() if len(w) > 2]
    if not words:
        return 0.0
    return sum(f" {w} " in source for w in words) / len(words)


def _scalar(value: str | None, source: str) -> Confidence:
    if not value:
        return Confidence.LOW
    score = grounding(value, source)
    if score >= 1.0:
        return Confidence.HIGH
    return Confidence.MEDIUM if score >= 0.5 else Confidence.LOW


def _items(values: Iterable[str], source: str, *, partial: float = 0.6) -> Confidence:
    values = list(values)
    if not values:
        return Confidence.LOW
    found = sum(grounding(v, source) >= partial for v in values) / len(values)
    if found >= 0.8:
        return Confidence.HIGH
    return Confidence.MEDIUM if found >= 0.5 else Confidence.LOW


def job_posting_confidence(posting: JobPosting, source_text: str) -> dict[str, Confidence]:
    source = normalize(source_text)
    title = normalize(posting.title)
    if posting.role_family == RoleFamily.OTHER:
        family = Confidence.LOW
    elif any(normalize(k) in title for k in FAMILY_KEYWORDS.get(posting.role_family, ())):
        family = Confidence.HIGH
    else:
        family = Confidence.MEDIUM
    if posting.level is None:
        level = Confidence.LOW
    elif posting.level_label and grounding(posting.level_label, source) >= 1.0:
        level = Confidence.HIGH
    else:
        level = Confidence.MEDIUM
    company = (
        Confidence.LOW
        if posting.company_name.lower() == "unknown"
        else _scalar(posting.company_name, source)
    )
    return {
        "company_name": company,
        "title": _scalar(posting.title, source),
        "role_family": family,
        "level": level,
        "level_label": _scalar(posting.level_label, source),
        "team": _scalar(posting.team, source),
        "location": _scalar(posting.location, source),
        "must_have_skills": _items(posting.must_have_skills, source),
        "nice_to_have_skills": _items(posting.nice_to_have_skills, source),
        "responsibilities": _items(posting.responsibilities, source, partial=0.5),
    }


def resume_confidence(resume: Resume, source_text: str) -> dict[str, Confidence]:
    source = normalize(source_text)
    roles = [f"{r.title} {r.company}" for r in resume.roles]
    role_conf = (
        _items([r.company for r in resume.roles], source)
        if roles and _items([r.title for r in resume.roles], source) != Confidence.LOW
        else Confidence.LOW
    )
    years = [d[:4] for r in resume.roles for d in (r.start, r.end) if d]
    return {
        "summary": _scalar(resume.summary, source) if resume.summary else Confidence.MEDIUM,
        "roles": role_conf,
        "dates": _items(years, source, partial=1.0),
        "achievements": _items(
            [a for r in resume.roles for a in r.achievements], source, partial=0.5
        ),
        "skills": _items(resume.skills, source),
        "education": _items([e.institution for e in resume.education], source)
        if resume.education
        else Confidence.MEDIUM,
        "certifications": _items(resume.certifications, source)
        if resume.certifications
        else Confidence.MEDIUM,
    }
