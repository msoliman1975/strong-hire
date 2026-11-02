"""Rank compared resumes, explain the pick and find gap hints (RC-2 to RC-5). Code only.

Nothing here calls a model: every number and sentence comes from the stored gap analyses and
the parsed resumes.

- Pre-screen (RC-2): the job's must-have skills each resume mentions, with the IN-12 rule.
- Rank (RC-3): match score, then fewer must-haves never shown, then fewer high-severity gaps,
  then the main resume, then the name.
- Hints (RC-4): a gap of the focus resume is covered by another resume when that resume's
  analysis rates the same requirement meets or exceeds (70 or more; a rating of 2 or 3 needs
  evidence found in that resume, GA-1). The evidence is matched to that resume's line.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field

from strong_api.resume_checks.checks import mentions
from strong_core.schemas import GapAnalysis, JobPosting, Resume, ResumeRole, Severity

COVERED_SCORE = 70  # points for rating 2 (meets it); 3 is 100
LINE_MATCH = 0.6  # share of the evidence words a resume line must contain
SEVERITY_ORDER = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}

_WORD = re.compile(r"[a-z0-9][a-z0-9+#.%]*")


@dataclass
class Candidate:
    """One compared resume with what is known about it."""

    resume_id: uuid.UUID
    name: str
    is_main: bool
    resume: Resume | None  # None when deleted
    analysis: GapAnalysis | None  # set when its analysis is ready
    must_missing: list[str] = field(default_factory=list)
    must_total: int = 0

    @property
    def must_shown(self) -> int:
        return self.must_total - len(self.must_missing)

    @property
    def high_gaps(self) -> int | None:
        if self.analysis is None:
            return None
        return sum(1 for g in self.analysis.gaps if g.severity == Severity.HIGH)


@dataclass(frozen=True)
class Source:
    resume_id: uuid.UUID
    resume_name: str
    line: str
    place: str  # "skills" or "achievement"
    company: str | None
    can_add: bool
    in_resume: bool = False  # the focus resume already has this line


@dataclass(frozen=True)
class Hint:
    key: str
    summary: str
    severity: Severity
    related_requirement: str | None
    source: Source | None
    listed_in: list[str] = field(default_factory=list)
    """Resumes (the focus first) that name the requirement, by the IN-12 rule."""


def words(text: str) -> set[str]:
    return {w.rstrip(".") for w in _WORD.findall(text.lower())} - {""}


def must_haves(posting: JobPosting | None) -> list[str]:
    if posting is None:
        return []
    return [s for s in dict.fromkeys(posting.must_have_skills) if s.strip()]


def prescreen(candidate: Candidate, posting: JobPosting | None) -> None:
    """RC-2: count the must-haves the resume shows, with the resume check's rule (IN-12)."""
    wanted = must_haves(posting)
    candidate.must_total = len(wanted)
    if candidate.resume is None:
        candidate.must_missing = list(wanted)
        return
    candidate.must_missing = [s for s in wanted if not mentions(candidate.resume, s)]


def ranked(candidates: list[Candidate]) -> list[Candidate]:
    """RC-3: the ready candidates, best first."""
    ready = [c for c in candidates if c.analysis is not None and c.resume is not None]

    def key(c: Candidate) -> tuple[int, int, int, bool, str]:
        assert c.analysis is not None
        return (
            -c.analysis.match_score,
            len(c.must_missing),
            c.high_gaps or 0,
            not c.is_main,
            c.name,
        )

    return sorted(ready, key=key)


def names(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def reason(order: list[Candidate]) -> str | None:
    """RC-3: why the first resume fits best, from the scores and the must-haves."""
    if not order:
        return None
    best, others = order[0], order[1:]
    assert best.analysis is not None
    if not others:
        score = best.analysis.match_score
        return f"{best.name} is the only resume with a finished analysis (match {score})."
    scores = ", ".join(f"{o.name} {o.analysis.match_score}" for o in others if o.analysis)
    text = f"{best.name} fits best: match {best.analysis.match_score}, against {scores}."
    if best.must_total:
        text += f" It shows {best.must_shown} of {best.must_total} must-haves."
    # A must-have every other resume lacks and this one shows.
    missing_elsewhere = set.intersection(*(set(o.must_missing) for o in others))
    only_best = [s for s in missing_elsewhere if s not in best.must_missing]
    if only_best:
        text += f" Only this resume shows {names(sorted(only_best)[:3])}."
    runner = others[0].analysis
    if runner is not None and runner.match_score == best.analysis.match_score:
        text += (
            " The scores tie, so the resume showing more must-haves and fewer serious gaps wins."
        )
    return text


def hint_key(resume_id: uuid.UUID, summary: str) -> str:
    digest = hashlib.sha1(summary.strip().lower().encode("utf-8")).hexdigest()[:12]
    return f"{resume_id.hex[:8]}-{digest}"


def _company(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _overlap(evidence: set[str], line: str) -> float:
    if not evidence:
        return 0.0
    return len(evidence & words(line)) / len(evidence)


def _source_line(resume: Resume, evidence: str) -> tuple[str, str, ResumeRole | None] | None:
    """The resume line the evidence quotes: (line, place, role). None when no line matches."""
    found = words(evidence)
    best: tuple[float, str, str, ResumeRole | None] | None = None
    options: list[tuple[str, str, ResumeRole | None]] = [(s, "skills", None) for s in resume.skills]
    for r in resume.roles:
        options += [(a, "achievement", r) for a in r.achievements]
        options += [(s, "skills", None) for s in r.skills]
    for line, place, owner in options:
        score = _overlap(found, line)
        if score >= LINE_MATCH and (best is None or score > best[0]):
            best = (score, line, place, owner)
    return None if best is None else (best[1], best[2], best[3])


def can_add(target: Resume, line: str, place: str, company: str | None) -> bool:
    """RC-4: a skill the target lacks, or an achievement at a company the target also lists."""
    if place == "skills":
        have = {s.strip().lower() for s in target.skills}
        have |= {s.strip().lower() for r in target.roles for s in r.skills}
        return line.strip().lower() not in have
    role = matching_role(target, company)
    if role is None:
        return False
    return line.strip().lower() not in {a.strip().lower() for a in role.achievements}


def matching_role(target: Resume, company: str | None) -> ResumeRole | None:
    """The target's role at the same company, most recent first (roles are listed newest first)."""
    if not company:
        return None
    key = _company(company)
    return next((r for r in target.roles if _company(r.company) == key), None)


def hints(focus: Candidate, others: list[Candidate]) -> list[Hint]:
    """RC-4, RC-5: the focus resume's gaps, most severe first, each with the other resume that
    covers it when there is one."""
    if focus.analysis is None or focus.resume is None:
        return []
    out: list[Hint] = []
    gaps = sorted(focus.analysis.gaps, key=lambda g: SEVERITY_ORDER.get(g.severity, 3))
    for gap in gaps:
        out.append(
            Hint(
                key=hint_key(focus.resume_id, gap.summary),
                summary=gap.summary,
                severity=gap.severity,
                related_requirement=gap.related_requirement,
                source=_cover(focus.resume, gap.related_requirement, others),
                listed_in=_listed_in(gap.related_requirement, [focus, *others]),
            )
        )
    return out


def _listed_in(requirement: str | None, candidates: list[Candidate]) -> list[str]:
    """RC-5: the resumes that name the requirement somewhere (skills, titles, lines), so a gap
    the analysis found is not shown as missing from resumes that list it."""
    if not requirement:
        return []
    return [c.name for c in candidates if c.resume is not None and mentions(c.resume, requirement)]


def in_resume(target: Resume, line: str, place: str) -> bool:
    """RC-4: the target resume already has this line (a skill anywhere, or an achievement in any
    role)."""
    wanted = line.strip().lower()
    if place == "skills":
        have = [*target.skills, *(s for r in target.roles for s in r.skills)]
    else:
        have = [a for r in target.roles for a in r.achievements]
    return wanted in {h.strip().lower() for h in have}


def _cover(target: Resume, requirement: str | None, others: list[Candidate]) -> Source | None:
    if not requirement:
        return None
    wanted = requirement.strip().lower()
    best: tuple[int, Candidate, str] | None = None
    for other in others:
        if other.analysis is None or other.resume is None:
            continue
        for match in other.analysis.requirement_breakdown:
            if match.requirement.strip().lower() != wanted or not match.evidence:
                continue
            if match.score >= COVERED_SCORE and (best is None or match.score > best[0]):
                best = (match.score, other, match.evidence)
    if best is None:
        return None
    _, other, evidence = best
    assert other.resume is not None
    located = _source_line(other.resume, evidence)
    if located is None:
        return Source(
            resume_id=other.resume_id,
            resume_name=other.name,
            line=evidence,
            place="achievement",
            company=None,
            can_add=False,
            in_resume=in_resume(target, evidence, "achievement"),
        )
    line, place, role = located
    company = role.company if role is not None else None
    present = in_resume(target, line, place)
    return Source(
        resume_id=other.resume_id,
        resume_name=other.name,
        line=line,
        place=place,
        company=company,
        can_add=not present and can_add(target, line, place, company),
        in_resume=present,
    )


def add_line(target: Resume, source: Source) -> Resume:
    """RC-4: the target resume with the line copied in, unchanged."""
    if source.place == "skills":
        return target.model_copy(update={"skills": [*target.skills, source.line]})
    role = matching_role(target, source.company)
    if role is None:
        raise ValueError("no role at that company")
    roles = [
        r.model_copy(update={"achievements": [*r.achievements, source.line]}) if r is role else r
        for r in target.roles
    ]
    return target.model_copy(update={"roles": roles})
