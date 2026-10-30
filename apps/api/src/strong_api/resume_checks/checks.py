"""RM-5: the rule-based resume check, a port of apps/web/src/pages/onboarding/resumeChecks.ts.

Rules, keys and messages are identical to the web check: shared cases in
apps/api/tests/fixtures/resume_checks/ run against both implementations. Deterministic, no model
calls. Each issue has a stable key built from its type and the fields involved (roles by company
and title, not by position), so an accepted issue stays accepted when the user edits something
else. Change the rules in both files together.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from strong_core.schemas import JobPosting, Level, Resume, ResumeRole

IssueGroup = Literal["dates", "detail", "level", "consistency", "job"]
Severity = Literal["high", "medium", "low"]
TargetField = Literal["start", "end", "title", "achievement", "achievements"]


class _Model(BaseModel):
    # snake_case in the API, camelCase in the shared fixtures (the web check's field names).
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class IssueTarget(_Model):
    """Where Fix goes: a field on a role card, the summary, or the skills card."""

    section: Literal["summary", "skills", "role"]
    role: int | None = None
    field: TargetField | None = None
    item: int | None = None


class AcceptReason(_Model):
    code: str = Field(description="Stored with the accepted key; letters and dashes only.")
    label: str


class GapPeriod(_Model):
    from_: str = Field(alias="from", serialization_alias="from")
    to: str


class ResumeIssue(_Model):
    key: str
    group: IssueGroup
    severity: Severity = Field(description='"high" draws the red stripe.')
    title: str
    detail: str
    why: str
    fix_label: str
    accept_label: str
    target: IssueTarget
    roles: list[int] = Field(description="Every role the issue is about.")
    field_note: str | None = None
    items: list[int] | None = None
    gap: GapPeriod | None = None
    reasons: list[AcceptReason] | None = None


MISSING_DATE_REASONS = [
    AcceptReason(code="on-purpose", label="Left out on purpose (age bias)"),
    AcceptReason(code="dont-remember", label="I don't remember"),
]

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_DATE = re.compile(r"^(\d{4})(?:-(0[1-9]|1[0-2]))?$")

GAP_MONTHS = 3
"""Gaps longer than this many months are reported."""
SHORT_SUMMARY_WORDS = 12
"""A summary shorter than this many words is "very short"."""
KEY_MAX = 200
"""The API stores keys of up to 200 characters."""

_F = re.IGNORECASE | re.ASCII


@dataclass(frozen=True)
class _Parsed:
    year: int
    month: int | None


@dataclass
class _Span:
    role: int
    start: int
    end: int


def _parse(value: str | None) -> _Parsed | None:
    m = _DATE.match(value.strip()) if value else None
    return _Parsed(int(m[1]), int(m[2]) if m[2] else None) if m else None


def _index(p: _Parsed, side: Literal["early", "late"]) -> int:
    """Months since year 0. A year alone counts as January or December."""
    month = p.month if p.month is not None else (1 if side == "early" else 12)
    return p.year * 12 + month - 1


def format_date(value: str | None) -> str:
    """'Mar 2022', or '2014' for a year alone."""
    p = _parse(value)
    if p is None:
        return value or ""
    return f"{MONTHS[p.month - 1]} {p.year}" if p.month else str(p.year)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _slug(text: str) -> str:
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", text.lower()))


_COMPANY_SUFFIX = re.compile(r"\b(inc|llc|ltd|limited|gmbh|corp|corporation|co|plc|sa|ag)\b\.?", _F)


def _company_key(company: str) -> str:
    """Company names compared loosely: "Acme Inc." and "ACME" are the same company."""
    return _slug(_COMPANY_SUFFIX.sub("", company)) or _slug(company)


def role_ids(roles: list[ResumeRole]) -> list[str]:
    """A stable id per role: company and title, with a counter when the same pair repeats."""
    seen: dict[str, int] = {}
    ids: list[str] = []
    for r in roles:
        base = f"{_company_key(r.company) or 'role'}/{_slug(r.title) or 'untitled'}"
        n = seen.get(base, 0) + 1
        seen[base] = n
        ids.append(base if n == 1 else f"{base}#{n}")
    return ids


def _role_namer(roles: list[ResumeRole]):  # type: ignore[no-untyped-def]
    counts: dict[str, int] = {}
    for r in roles:
        counts[_company_key(r.company)] = counts.get(_company_key(r.company), 0) + 1

    def name(r: ResumeRole) -> str:
        company = r.company.strip()
        title = r.title.strip()
        if company and title and counts.get(_company_key(r.company), 0) > 1:
            return f"{title} at {company}"
        return company or title or "this role"

    return name


_RESULT = re.compile(
    r"\d|%|\$|€|£|\b(one|two|three|four|five|six|seven|eight|nine|ten|twice|half|third|quarter"
    r"|double[ds]?|tripled?|halved)\b|\b(cut|reduc|increas|grew|rais|sav|lower|boost|doubl|fell"
    r"|dropp|decreas|accelerat|shorten)\w*",
    _F,
)
_NUMBER = re.compile(r"\d|%|\$|€|£")

NO_RESULT_WHY = (
    "Say what changed. A number helps if you have one, but you do not need one: name the measure "
    'that moved ("improved task success, time on task and error rate in usability benchmarks"), '
    'the direction ("cut support tickets after launch"), or the scale and scope ("for 3 product '
    'teams", "used by every store in the region"). Results are what interviewers remember.'
)
_WE = re.compile(r"\b(we|our|us)\b", _F)
_I = re.compile(
    r"\b(i|my|me)\b|^\s*(led|built|owned|designed|drove|ran|wrote|managed|created|launched"
    r"|shipped|hired|cut|grew|started|founded|mentored|coached)\b",
    _F,
)
_SCOPE = re.compile(
    r"\b(team of|teams?|engineers|reports|direct reports|hired|managed|mentor\w*|coach\w*|budget"
    r"|\$\d|million|cross[- ](team|functional)|org(anization)?[- ]wide|company[- ]wide"
    r"|across \w+ teams|stakeholders|roadmap|strategy|headcount|led)\b",
    _F,
)
_SENIOR_TITLE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|head|director|vp|chief|architect)\b", _F
)


def _senior_target(job: JobPosting | None, roles: list[ResumeRole]) -> str | None:
    if job is not None and job.level in (Level.SENIOR, Level.STAFF_PRINCIPAL):
        return job.level_label or ("Senior" if job.level == Level.SENIOR else "Staff")
    if job is not None and job.level is not None:
        return None
    if job is not None and job.title and _SENIOR_TITLE.search(job.title):
        return job.title
    if job is None and roles and _SENIOR_TITLE.search(roles[0].title):
        return roles[0].title
    return None


def _mentions(resume: Resume, skill: str) -> bool:
    """Does the resume mention the skill anywhere: skills, role skills, achievements, titles or
    the summary?"""
    needle = skill.strip().lower()
    if not needle:
        return True
    word = re.compile(rf"(^|[^a-z0-9+#]){re.escape(needle)}($|[^a-z0-9+#])", _F)
    texts = [resume.summary or "", *resume.skills]
    for r in resume.roles:
        texts += [r.title, *r.skills, *r.achievements]
    texts += resume.certifications
    return any(word.search(t) for t in texts)


def _truncate(text: str, limit: int) -> str:
    t = text.strip()
    return f"{t[: limit - 1].rstrip()}…" if len(t) > limit else t


def fit_key(key: str) -> str:
    """A key cut to KEY_MAX, ending in a hash of the whole key (FNV-1a over UTF-16 code units,
    as the web check computes it)."""
    if len(key) <= KEY_MAX:
        return key
    h = 0x811C9DC5
    units = key.encode("utf-16-le")
    for i in range(0, len(units), 2):
        h = ((h ^ int.from_bytes(units[i : i + 2], "little")) * 0x01000193) & 0xFFFFFFFF
    digest = f"{h:08x}"
    return f"{key[: KEY_MAX - len(digest) - 1]}~{digest}"


_SEVERITY = {"high": 0, "medium": 1, "low": 2}


def check_resume(resume: Resume, *, today: str, job: JobPosting | None = None) -> list[ResumeIssue]:
    """Runs every check. `today` is this month as YYYY-MM. Roles keep their order and indexes,
    so `target.role` points into `resume.roles`."""
    issues: list[ResumeIssue] = []
    now_p = _parse(today)
    if now_p is None:
        raise ValueError(f"today must be YYYY-MM, got {today}")
    now = _index(now_p, "late")
    roles = resume.roles
    ids = role_ids(roles)
    role_name = _role_namer(roles)

    def role_target(i: int, field: TargetField, item: int | None = None) -> IssueTarget:
        return IssueTarget(section="role", role=i, field=field, item=item)

    # ---- Dates, one role at a time.
    for i, r in enumerate(roles):
        s = _parse(r.start)
        e = _parse(r.end)
        name = role_name(r)
        if s and e and _index(e, "late") < _index(s, "early"):
            issues.append(
                ResumeIssue(
                    key=f"dates.end-before-start:{ids[i]}",
                    group="dates",
                    severity="high",
                    title=f"{name} ends before it starts",
                    detail=f"{format_date(r.start)} to {format_date(r.end)}",
                    why="An end date before the start date looks like a typo, and screeners "
                    "notice.",
                    fix_label="Fix the date",
                    accept_label="Accept as it is",
                    target=role_target(i, "end"),
                    roles=[i],
                    field_note="Ends before it starts",
                )
            )
        for side, p in (("start", s), ("end", e)):
            if p and (_index(p, "early") if p.month else p.year * 12) > now:
                issues.append(
                    ResumeIssue(
                        key=f"dates.future:{ids[i]}:{side}",
                        group="dates",
                        severity="high",
                        title=f"A future date on {name}",
                        detail=f"{'Starts' if side == 'start' else 'Ends'} "
                        f"{format_date(r.start if side == 'start' else r.end)}",
                        why="Dates after today read as a mistake. If the role is current, leave "
                        "the end empty.",
                        fix_label="Fix the date",
                        accept_label="Accept as it is",
                        target=role_target(i, "start" if side == "start" else "end"),
                        roles=[i],
                        field_note="This date is in the future",
                    )
                )
        if (s and s.month is None) or (e and e.month is None):
            issues.append(
                ResumeIssue(
                    key=f"dates.year-only:{ids[i]}",
                    group="dates",
                    severity="low",
                    title=f"Years only on {name}",
                    detail=f"{format_date(r.start) or '?'} to "
                    f"{format_date(r.end) if r.end else 'now'}",
                    why="Years alone can hide up to 11 months on each side. Screeners often ask "
                    "for the months.",
                    fix_label="Add the months",
                    accept_label="Accept, years are enough",
                    target=role_target(i, "start" if s and s.month is None else "end"),
                    roles=[i],
                    field_note="Add the month, for example 2016-04",
                )
            )
        if not s:
            issues.append(
                ResumeIssue(
                    key=f"dates.missing-start:{ids[i]}",
                    group="dates",
                    severity="medium",
                    title=f"No start date on {name}",
                    detail="We could not find when this role started.",
                    why="Without dates, interviewers cannot tell how long you held the role, so "
                    "they may ask. Leaving old dates off on purpose is fine: accept it and say "
                    "why, and be ready to answer.",
                    fix_label="Add the date",
                    accept_label="Accept as it is",
                    reasons=MISSING_DATE_REASONS,
                    target=role_target(i, "start"),
                    roles=[i],
                    field_note="Add a start date",
                )
            )

    # ---- Dates across roles: overlaps and gaps. Years alone are read in the role's favor.
    spans: list[_Span] = []
    for i, r in enumerate(roles):
        s = _parse(r.start)
        if not s:
            continue
        e = _parse(r.end) if r.end else now_p
        if not e:
            continue
        spans.append(_Span(i, _index(s, "early"), _index(e, "late") if r.end else now))

    def strict(r: ResumeRole) -> tuple[int, int]:
        """A year alone counts as its latest start and earliest end."""
        s = _parse(r.start)
        assert s is not None
        e = _parse(r.end) if r.end else now_p
        return _index(s, "late"), (_index(e, "early") if r.end and e else now)

    for a in range(len(spans)):
        for b in range(a + 1, len(spans)):
            x = roles[spans[a].role]
            y = roles[spans[b].role]
            px = strict(x)
            qy = strict(y)
            months = min(px[1], qy[1]) - max(px[0], qy[0])
            # A one-month handover is normal.
            if months < 2:
                continue
            first, second = (
                (spans[a].role, spans[b].role) if px[0] <= qy[0] else (spans[b].role, spans[a].role)
            )
            earlier = roles[first]
            later = roles[second]
            pair = "+".join(sorted([ids[first], ids[second]]))
            both = not x.end and not y.end
            issues.append(
                ResumeIssue(
                    key=f"dates.overlap:{pair}",
                    group="dates",
                    severity="high",
                    title="Two current roles" if both else "Overlapping roles",
                    detail=(
                        f"{role_name(earlier)} and {role_name(later)} both have no end date"
                        if both
                        else f"{role_name(earlier)} ends "
                        f"{format_date(earlier.end) if earlier.end else 'now'}, "
                        f"{role_name(later)} starts {format_date(later.start)}"
                    ),
                    why="Interviewers ask about overlaps. If you really held both, say so; "
                    "otherwise fix the date.",
                    fix_label="Fix the date",
                    accept_label="Accept: I held both",
                    target=role_target(first, "end"),
                    roles=[first, second],
                    field_note=f"Overlaps {role_name(later)} by {_plural(months, 'month')}",
                )
            )

    # Gaps: merge the spans in time order; a gap is a stretch no role covers.
    cover: _Span | None = None
    for span in sorted(spans, key=lambda sp: (sp.start, sp.end)):
        if cover:
            months = span.start - cover.end - 1
            if months > GAP_MONTHS:
                before = roles[cover.role]
                after = roles[span.role]
                issues.append(
                    ResumeIssue(
                        key=f"dates.gap:{ids[cover.role]}>{ids[span.role]}",
                        group="dates",
                        severity="medium",
                        title=f"A {months}-month gap",
                        detail=f"{format_date(before.end)} to {format_date(after.start)}, between "
                        f"{role_name(before)} and {role_name(after)}",
                        why="Gaps over 3 months come up in screens. Check the dates, or accept it "
                        "and practice your answer (study, travel, caring, a career break).",
                        fix_label="Check the dates",
                        accept_label="Accept, I'll explain it",
                        target=role_target(span.role, "start"),
                        roles=[cover.role, span.role],
                        gap=GapPeriod(from_=format_date(before.end), to=format_date(after.start)),
                    )
                )
        if not cover or span.end > cover.end:
            cover = span

    # A current role not marked: nothing is current, and the newest role ended this month or last.
    if roles and all(r.end for r in roles):
        newest = -1
        newest_end: float = float("-inf")
        for i, r in enumerate(roles):
            e = _parse(r.end)
            if e and _index(e, "late") > newest_end:
                newest_end = _index(e, "late")
                newest = i
        if newest >= 0 and now - 1 <= newest_end <= now:
            r = roles[newest]
            issues.append(
                ResumeIssue(
                    key=f"dates.current-not-marked:{ids[newest]}",
                    group="dates",
                    severity="medium",
                    title=f"Is {role_name(r)} your current role?",
                    detail=f"It ends {format_date(r.end)}, and no role is marked current.",
                    why="If you still work there, leave the end date empty so interviewers read "
                    "it as your current job.",
                    fix_label="Mark as current",
                    accept_label="Accept, I left",
                    target=role_target(newest, "end"),
                    roles=[newest],
                    field_note="Leave empty if you still work here",
                )
            )

    # ---- Detail.
    for i, r in enumerate(roles):
        name = role_name(r)
        items = [a.strip() for a in r.achievements if a.strip()]
        if len(items) < 2:
            issues.append(
                ResumeIssue(
                    key=f"detail.few-achievements:{ids[i]}",
                    group="detail",
                    severity="medium",
                    title=f"No achievements on {name}"
                    if not items
                    else f"One achievement on {name}",
                    detail="Roles read best with 2 to 5 achievements.",
                    why="Interviewers pick their questions from your achievements. A thin role "
                    "gives them little to ask about, and you little to show.",
                    fix_label="Add an achievement",
                    accept_label="Accept as it is",
                    target=role_target(i, "achievements"),
                    roles=[i],
                )
            )
        no_result = [j for j, a in enumerate(r.achievements) if a.strip() and not _RESULT.search(a)]
        if no_result:
            issues.append(
                ResumeIssue(
                    key=f"detail.no-result:{ids[i]}",
                    group="detail",
                    severity="low",
                    title=(
                        f"An achievement without a result at {name}"
                        if len(no_result) == 1
                        else f"{len(no_result)} achievements without a result at {name}"
                    ),
                    detail=f'"{_truncate(r.achievements[no_result[0]], 60)}"',
                    why=NO_RESULT_WHY,
                    fix_label="Add a result",
                    accept_label="Accept as it is",
                    target=role_target(i, "achievement", no_result[0]),
                    roles=[i],
                    items=no_result,
                    field_note="No result yet. What changed, for whom, or how big was it?",
                )
            )
        we = [j for j, a in enumerate(r.achievements) if _WE.search(a)]
        if we and not any(_I.search(a) for a in r.achievements):
            j = we[0]
            issues.append(
                ResumeIssue(
                    key=f"detail.we-no-i:{ids[i]}",
                    group="detail",
                    severity="low",
                    title=f'"We" but never "I" at {name}',
                    detail=f'"{_truncate(r.achievements[j], 60)}"',
                    why="Interviewers want your part. Say what you did, then what the team "
                    "achieved.",
                    fix_label="Say what you did",
                    accept_label="Accept as it is",
                    target=role_target(i, "achievement", j),
                    roles=[i],
                    items=we,
                    field_note='Says "we". What was your part?',
                )
            )

    summary = (resume.summary or "").strip()
    words = len(re.split(r"\s+", summary)) if summary else 0
    if not summary:
        issues.append(
            ResumeIssue(
                key="detail.summary-missing",
                group="detail",
                severity="medium",
                title="No summary",
                detail="Your resume has no intro.",
                why='"Tell me about yourself" opens most interviews. Two or three lines here give '
                "you a ready answer.",
                fix_label="Write a summary",
                accept_label="Accept, no summary",
                target=IssueTarget(section="summary"),
                roles=[],
            )
        )
    elif words < SHORT_SUMMARY_WORDS:
        issues.append(
            ResumeIssue(
                key="detail.summary-short",
                group="detail",
                severity="low",
                title="A very short summary",
                detail=f"{_plural(words, 'word')}.",
                why="Say who you are, your years and field, and one result. It sets up your answer "
                'to "tell me about yourself".',
                fix_label="Add to the summary",
                accept_label="Accept as it is",
                target=IssueTarget(section="summary"),
                roles=[],
                field_note="Very short",
            )
        )
    elif not _NUMBER.search(summary):
        issues.append(
            ResumeIssue(
                key="detail.summary-no-number",
                group="detail",
                severity="low",
                title="Summary has no number",
                detail="No years, size or result in your intro.",
                why="One number (years, team size, a result) makes the intro concrete.",
                fix_label="Add a number",
                accept_label="Accept as it is",
                target=IssueTarget(section="summary"),
                roles=[],
                field_note="No number in your summary",
            )
        )

    # ---- Fit for level.
    target = _senior_target(job, roles)
    if target:
        texts = [summary, *(a for r in roles for a in r.achievements)]
        if not any(_SCOPE.search(t) for t in texts):
            issues.append(
                ResumeIssue(
                    key="level.no-scope",
                    group="level",
                    severity="medium",
                    title="No scope for a senior role",
                    detail=f"Target: {target}. No team size, budget or cross-team work.",
                    why="Senior interviews test scope. Show how many people, teams or how much "
                    "money your work touched.",
                    fix_label="Add scope",
                    accept_label="Accept as it is",
                    target=role_target(0, "achievements")
                    if roles
                    else IssueTarget(section="summary"),
                    roles=[0] if roles else [],
                )
            )

    # ---- Consistency.
    listed = {s.strip().lower() for s in resume.skills}
    used: list[str] = []
    for r in roles:
        for skill in r.skills:
            k = skill.strip().lower()
            if k and k not in listed and not any(u.lower() == k for u in used):
                used.append(skill.strip())
    if used:
        issues.append(
            ResumeIssue(
                key=f"consistency.skills-missing:{','.join(sorted(_slug(u) for u in used))}",
                group="consistency",
                severity="low",
                title="A skill missing from Skills"
                if len(used) == 1
                else f"{len(used)} skills missing from Skills",
                detail=", ".join(used),
                why="Recruiters and match tools read the Skills list first. Skills you used in a "
                "role belong there too.",
                fix_label="Open Skills",
                accept_label="Accept as it is",
                target=IssueTarget(section="skills"),
                roles=[],
            )
        )

    by_company: dict[str, list[int]] = {}
    for i, r in enumerate(roles):
        k = _company_key(r.company)
        if k:
            by_company.setdefault(k, []).append(i)
    for company, members in by_company.items():
        if len(members) < 2:
            continue
        issues.append(
            ResumeIssue(
                key=f"consistency.same-company:{company}",
                group="consistency",
                severity="low",
                title=f"{roles[members[0]].company} listed {len(members)} times",
                detail=", ".join(roles[i].title for i in members),
                why="If these are promotions, interviewers like seeing them under one company. If "
                "one is a duplicate, remove it.",
                fix_label="Open the role",
                accept_label="Accept: separate roles",
                target=role_target(members[1], "title"),
                roles=members,
            )
        )

    # ---- Against a job.
    missing = [
        s for s in (job.must_have_skills if job else []) if s.strip() and not _mentions(resume, s)
    ]
    if missing:
        issues.append(
            ResumeIssue(
                key=f"job.must-have:{','.join(sorted(_slug(m) for m in missing))}",
                group="job",
                severity="medium",
                title="A must-have skill the resume never shows"
                if len(missing) == 1
                else f"{len(missing)} must-have skills the resume never shows",
                detail=", ".join(missing),
                why="The job lists these as must-haves. If you have them, add them to Skills or "
                "to an achievement; if not, prepare to talk about it.",
                fix_label="Open Skills",
                accept_label="Accept, I'll address it",
                target=IssueTarget(section="skills"),
                roles=[],
            )
        )

    # Most serious first; the sort is stable, so ties keep the order above.
    issues.sort(key=lambda i: _SEVERITY[i.severity])
    for issue in issues:
        issue.key = fit_key(issue.key)
    return issues
