"""Admin Part 3 (AD-5): the AI coach, practice readiness by skill and the recruiter screen setup.

    GET /admin/part3/coach?weeks=8    coach sessions and minutes per UTC week (Monday start),
                                      coach minutes against plan caps, cost per coach session from
                                      usage events, and the latest coach eval results (CO-9)
    GET /admin/part3/readiness        practice readiness by skill across users, aggregate only

The session detail and replay pages also show a session's brief and rubric (`session_setup`):
the rubric (a prompt file, no user data) always, the brief only under the transcript's consent
rule, since its questions come from the user's job and resume.

Aggregate only. No coach turn text, take text or story text is selected here: coach sessions
give counts, minutes, channels and timestamps; usage events give cost; scorecards give only the
numeric competency scores. A test checks that no admin endpoint returns that text.

Cost per coach session. The coach engine writes usage events with role `coach` and no
session_id (usage_context(org_id)), and the voice coach writes its STT and TTS events the same
way. Interview sessions always set session_id, so coach cost = the cost of events with role
`coach`, plus `stt`/`tts` events with no session_id, in the weeks shown, divided by the coach
sessions created in those weeks.

Minutes against plan caps. Coach sessions record minutes on their own row and do not use plan
minutes (billing rules for coach time are undecided). To inform that decision, for each user on a
paid or comp plan this compares the coach minutes in the current plan period with the plan cap,
and counts users who would pass their cap if coach minutes counted.

Readiness by skill. Realistic sessions only (PR-1, RD-1), no `tiny` or `local` dev data (PL-6),
scored in the last 90 days. Per skill: each user's mean rubric score (1 to 4); a user with fewer
than READY_MIN_SESSIONS scored sessions for the skill is "not enough data". It is a practice
estimate (RD-3), not the per-interview readiness formula (S34), which weights recent sessions.

Coach eval results come from the eval harness's JSON reports (evals/reports, or EVAL_REPORTS_DIR):
the newest report with coach metrics. Only the metric numbers are read, never the transcripts the
report also holds.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.admin import metrics as m
from strong_api.admin.deps import Admin
from strong_api.admin.part1 import week_start
from strong_api.admin.schemas import AdminRubric, SessionSetup
from strong_api.auth.deps import DbSession
from strong_api.billing.entitlements import get_entitlement
from strong_core.config import get_settings
from strong_core.db.models import (
    CoachSession,
    InterviewSession,
    Scorecard,
    Subscription,
    UsageEvent,
)
from strong_core.gateway import CapabilityTier
from strong_core.prompts import PromptNotFoundError, load_prompt
from strong_core.schemas import InterviewerBrief, Mode
from strong_core.schemas.enums import CoachStyle, Competency, SessionChannel

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

DEV_PROFILES = frozenset({"tiny", "local"})  # PL-6: development data, never in real trends
EVAL_DEV_PROFILES = frozenset({"fake", "tiny", "local"})
READY_WINDOW = timedelta(days=90)
READY_MIN_SESSIONS = 2
READY_BAR = 3.0  # a rubric score of 3 meets the bar
PLAN_PERIOD_FALLBACK = timedelta(days=30)
MAX_EVAL_RUNS = 5

COST_NOTE = (
    "Usage events with role coach, plus STT and TTS events with no interview session (the voice "
    "coach), divided by the coach sessions started in the weeks shown."
)
COST_EMPTY = "No coach session was started in the weeks shown."
CAP_NOTE = (
    "Coach minutes in each paid user's current plan period, as a share of their plan caps. Coach "
    "minutes do not use plan minutes today."
)
CAP_EMPTY = "No user is on a paid or comp plan."
EVAL_EMPTY = "No coach eval run yet. Run ./scripts/eval.ps1 -Suite coach."
READY_NOTE = (
    "Practice estimate from Realistic sessions only, last 90 days, without development data. "
    f"Fewer than {READY_MIN_SESSIONS} scored sessions for a skill is not enough data."
)


# ---------------------------------------------------------------- coach


class CoachWeek(BaseModel):
    week_start: datetime = Field(description="Monday 00:00 UTC")
    sessions: int = Field(description="Coach sessions started that week")
    minutes: int = Field(description="Their recorded minutes")
    voice: int
    text: int
    users: int = Field(description="Distinct users with a coach session that week")


class CoachCapUse(BaseModel):
    paid_users: int = Field(description="Users on a paid or comp plan now")
    coach_minutes: int = Field(description="Their coach minutes in their current plan periods")
    interview_minutes: int = Field(description="Their plan minutes used in those periods")
    cap_minutes: int = Field(description="Sum of their plan caps, grants included")
    over_cap_if_counted: int = Field(
        description="Users whose interview plus coach minutes would pass their cap"
    )
    free_user_coach_minutes: int = Field(
        description="Coach minutes of users without a paid plan, in the weeks shown"
    )


class EvalMetric(BaseModel):
    key: str
    name: str
    value: float | None
    threshold: str
    passed: bool | None = Field(description="None: information only, or not measured")


class CoachEvalRun(BaseModel):
    file: str = Field(description="Report file name in evals/reports")
    suite: str
    profile: str
    started_at: str
    git_sha: str
    dev_data: bool = Field(description="PL-6: fake, tiny or local profile; not a launch result")
    passed: bool | None = Field(description="Every gated coach metric passed; None if none gated")
    metrics: list[EvalMetric] = Field(description="Coach metrics only (key starts with coach_)")


class CoachEvals(BaseModel):
    latest: CoachEvalRun | None
    runs: list[CoachEvalRun] = Field(description=f"Up to {MAX_EVAL_RUNS}, newest first")
    reason: str | None = Field(default=None, description="Why there is no result")


class Part3Coach(BaseModel):
    sessions: int = Field(description="Coach sessions started in the weeks shown")
    minutes: int
    users: int
    by_style: dict[CoachStyle, int] = Field(description="Every style is present")
    by_channel: dict[SessionChannel, int] = Field(description="Every channel is present")
    minutes_per_session: m.AdminMetric
    cost_per_session: m.AdminMetric
    cost_total_usd: float
    cap_share: m.AdminMetric = Field(description="Coach minutes as a share of plan caps")
    caps: CoachCapUse
    weeks: list[CoachWeek] = Field(description="Oldest first; the last is this week")
    evals: CoachEvals


def _utc(at: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as UTC."""
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


def eval_reports_dir() -> Path:
    """Where the eval harness writes its reports. Tests replace it."""
    configured = os.environ.get("EVAL_REPORTS_DIR")
    return Path(configured) if configured else get_settings().repo_root / "evals" / "reports"


def _eval_run(path: Path) -> CoachEvalRun | None:
    """The coach metrics of one report, or None when it has none or cannot be read."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("cannot read eval report %s", path, exc_info=True)
        return None
    if not isinstance(data, dict) or not isinstance(data.get("metrics"), list):
        return None
    metrics: list[EvalMetric] = []
    for item in data["metrics"]:
        if not isinstance(item, dict) or not str(item.get("key", "")).startswith("coach_"):
            continue
        value = item.get("value")
        passed = item.get("passed")
        metrics.append(
            EvalMetric(
                key=str(item["key"]),
                name=str(item.get("name") or item["key"]),
                value=float(value)
                if isinstance(value, int | float) and not isinstance(value, bool)
                else None,
                threshold=str(item.get("threshold") or ""),
                passed=passed if isinstance(passed, bool) else None,
            )
        )
    if not metrics:
        return None
    gated = [x.passed for x in metrics if x.passed is not None]
    profile = str(data.get("profile") or "")
    return CoachEvalRun(
        file=path.name,
        suite=str(data.get("suite") or ""),
        profile=profile,
        started_at=str(data.get("started_at") or ""),
        git_sha=str(data.get("git_sha") or ""),
        dev_data=profile in EVAL_DEV_PROFILES,
        passed=all(gated) if gated else None,
        metrics=metrics,
    )


def coach_evals(folder: Path) -> CoachEvals:
    """CO-9: the newest reports with coach metrics. A real (hosted) run is `latest` when one
    exists, else the newest development run."""
    runs: list[CoachEvalRun] = []
    if folder.is_dir():
        for path in folder.glob("*.json"):
            run = _eval_run(path)
            if run is not None:
                runs.append(run)
    runs.sort(key=lambda r: r.started_at, reverse=True)
    runs = runs[:MAX_EVAL_RUNS]
    if not runs:
        return CoachEvals(latest=None, runs=[], reason=EVAL_EMPTY)
    real = [r for r in runs if not r.dev_data]
    return CoachEvals(latest=real[0] if real else runs[0], runs=runs)


async def _cap_use(
    db: AsyncSession, now: datetime, first: datetime
) -> tuple[CoachCapUse, m.AdminMetric]:
    paid_orgs = set(await db.scalars(select(Subscription.org_id).distinct()))
    paid_orgs |= set(
        await db.scalars(
            select(CoachSession.org_id).where(CoachSession.created_at >= now - PLAN_PERIOD_FALLBACK)
        )
    )
    coach = cap = used = over = users = 0
    paid: set[uuid.UUID] = set()
    for org in paid_orgs:
        ent = await get_entitlement(db, org, now=now)
        if ent.plan != "paid":
            continue
        paid.add(org)
        since = ent.period_start or now - PLAN_PERIOD_FALLBACK
        mins = int(
            await db.scalar(
                select(func.coalesce(func.sum(CoachSession.minutes), 0)).where(
                    CoachSession.org_id == org, CoachSession.created_at >= since
                )
            )
            or 0
        )
        users += 1
        coach += mins
        cap += ent.minutes_cap
        used += ent.minutes_used
        if ent.minutes_used + mins > ent.minutes_cap:
            over += 1
    free_minutes = 0
    for org, mins in await db.execute(
        select(CoachSession.org_id, func.sum(CoachSession.minutes))
        .where(CoachSession.created_at >= first)
        .group_by(CoachSession.org_id)
    ):
        if org not in paid:
            free_minutes += int(mins or 0)
    caps = CoachCapUse(
        paid_users=users,
        coach_minutes=coach,
        interview_minutes=used,
        cap_minutes=cap,
        over_cap_if_counted=over,
        free_user_coach_minutes=free_minutes,
    )
    share = (
        m.AdminMetric(value=m.ratio(coach, cap), unit="pct", note=CAP_NOTE)
        if users
        else m.not_measured(CAP_EMPTY, unit="pct")
    )
    return caps, share


@router.get("/part3/coach")
async def get_part3_coach(
    _: Admin,
    db: DbSession,
    weeks: Annotated[int, Query(ge=1, le=52, description="How many weeks, this one included")] = 8,
) -> Part3Coach:
    """AD-5: coach sessions and minutes, minutes against plan caps, cost per coach session and
    the latest coach eval results."""
    now = m.now_utc()
    first = week_start(now) - timedelta(weeks=weeks - 1)
    starts = [first + timedelta(weeks=i) for i in range(weeks)]

    by_week: dict[int, CoachWeek] = {
        int(s.timestamp()): CoachWeek(week_start=s, sessions=0, minutes=0, voice=0, text=0, users=0)
        for s in starts
    }
    week_users: dict[int, set[uuid.UUID]] = defaultdict(set)
    by_style: dict[CoachStyle, int] = dict.fromkeys(CoachStyle, 0)
    by_channel: dict[SessionChannel, int] = dict.fromkeys(SessionChannel, 0)
    all_users: set[uuid.UUID] = set()
    total = minutes = 0
    rows = await db.execute(
        select(
            CoachSession.created_at,
            CoachSession.user_id,
            CoachSession.style,
            CoachSession.channel,
            CoachSession.minutes,
        ).where(CoachSession.created_at >= first)
    )
    for created, user_id, style, channel, mins in rows:
        key = int(week_start(_utc(created)).timestamp())
        week = by_week.get(key)
        if week is None:
            continue
        week.sessions += 1
        week.minutes += int(mins or 0)
        if SessionChannel(channel) == SessionChannel.VOICE:
            week.voice += 1
        else:
            week.text += 1
        week_users[key].add(user_id)
        by_style[CoachStyle(style)] += 1
        by_channel[SessionChannel(channel)] += 1
        all_users.add(user_id)
        total += 1
        minutes += int(mins or 0)
    for key, week in by_week.items():
        week.users = len(week_users[key])

    cost = m.money(
        await db.scalar(
            select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
                UsageEvent.created_at >= first,
                or_(
                    UsageEvent.role == "coach",
                    UsageEvent.session_id.is_(None) & UsageEvent.role.in_(("stt", "tts")),
                ),
            )
        )
    )
    per_session = (
        m.AdminMetric(value=m.ratio(cost, total), unit="usd", note=COST_NOTE)
        if total
        else m.not_measured(COST_EMPTY, unit="usd")
    )
    caps, share = await _cap_use(db, now, first)
    return Part3Coach(
        sessions=total,
        minutes=minutes,
        users=len(all_users),
        by_style=by_style,
        by_channel=by_channel,
        minutes_per_session=m.AdminMetric(
            value=m.ratio(minutes, total), unit="minutes", note="Recorded minutes per session."
        ),
        cost_per_session=per_session,
        cost_total_usd=round(cost, 6),
        cap_share=share,
        caps=caps,
        weeks=list(by_week.values()),
        evals=coach_evals(eval_reports_dir()),
    )


# ---------------------------------------------------------------- readiness


class SkillReadinessRow(BaseModel):
    competency: Competency
    users: int = Field(description="Users with at least one Realistic score for the skill")
    users_enough_data: int = Field(
        description=f"Of them, users with {READY_MIN_SESSIONS} or more scored sessions"
    )
    users_at_bar: int = Field(description="Of those, users whose mean score is 3 or more")
    mean_score: float | None = Field(description="Mean of the users' means, 1 to 4")
    sessions: int = Field(description="Realistic sessions that scored the skill")


class Part3Readiness(BaseModel):
    kind: str = Field(default="practice_estimate", description="RD-3: a practice estimate")
    note: str = READY_NOTE
    window_days: int
    min_sessions: int
    users: int = Field(description="Users with any Realistic score in the window")
    skills: list[SkillReadinessRow] = Field(description="Skills with any score, most users first")


def competency_scores(raw: Any) -> list[tuple[Competency, int]]:
    """(competency, score) pairs of a scorecard's competency_scores_json. Reads only the two
    fields, never the justification or the quotes."""
    out: list[tuple[Competency, int]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        score = item.get("score")
        try:
            comp = Competency(str(item.get("competency")))
        except ValueError:
            continue
        if isinstance(score, int) and not isinstance(score, bool) and 1 <= score <= 4:
            out.append((comp, score))
    return out


@router.get("/part3/readiness")
async def get_part3_readiness(_: Admin, db: DbSession) -> Part3Readiness:
    """AD-5: practice readiness by skill across users (RD-1), aggregate only."""
    since = m.now_utc() - READY_WINDOW
    rows = await db.execute(
        select(Scorecard.org_id, Scorecard.competency_scores_json)
        .join(InterviewSession, InterviewSession.id == Scorecard.session_id)
        .where(
            InterviewSession.mode == Mode.REALISTIC,
            Scorecard.created_at >= since,
            or_(
                InterviewSession.model_profile.is_(None),
                InterviewSession.model_profile.not_in(DEV_PROFILES),
            ),
        )
    )
    # scores[competency][org] = one score per session (a session's mean for the skill)
    scores: dict[Competency, dict[uuid.UUID, list[float]]] = defaultdict(lambda: defaultdict(list))
    users: set[uuid.UUID] = set()
    for org, raw in rows:
        per_skill: dict[Competency, list[int]] = defaultdict(list)
        for comp, score in competency_scores(raw):
            per_skill[comp].append(score)
        for comp, values in per_skill.items():
            scores[comp][org].append(sum(values) / len(values))
            users.add(org)

    skills: list[SkillReadinessRow] = []
    for comp, by_user in scores.items():
        enough = {u: v for u, v in by_user.items() if len(v) >= READY_MIN_SESSIONS}
        means = [sum(v) / len(v) for v in enough.values()]
        skills.append(
            SkillReadinessRow(
                competency=comp,
                users=len(by_user),
                users_enough_data=len(enough),
                users_at_bar=sum(1 for x in means if x >= READY_BAR),
                mean_score=round(sum(means) / len(means), 2) if means else None,
                sessions=sum(len(v) for v in by_user.values()),
            )
        )
    skills.sort(key=lambda s: (-s.users, s.competency.value))
    return Part3Readiness(
        window_days=READY_WINDOW.days,
        min_sessions=READY_MIN_SESSIONS,
        users=len(users),
        skills=skills,
    )


# ---------------------------------------------------------------- brief and rubric


_REF = re.compile(
    r"^(?P<role>[a-z_]+)/(?P<name>[a-z0-9_]+)(?:\.(?P<tier>small|medium|large))?\.v(?P<v>\d+)$"
)
# RS-2: the scorer's rubric prompt by type; the worker picks it the same way (RUBRIC_BY_TYPE).
RUBRIC_NAME = {"recruiter_screen": "rubric_recruiter_screen"}


def rubric_for(row: InterviewSession, card: Scorecard | None) -> AdminRubric | None:
    """The rubric the scorer used (the scorecard's rubric_version), else the current one."""
    if card is not None:
        match = _REF.match(card.rubric_version or "")
        if match is None:
            return None
        tier = CapabilityTier(match["tier"]) if match["tier"] else None
        try:
            prompt = load_prompt(match["role"], match["name"], int(match["v"]), tier=tier)
        except PromptNotFoundError:
            return AdminRubric(ref=card.rubric_version, text=None, scored=True)
        return AdminRubric(ref=card.rubric_version, text=prompt.text, scored=True)
    try:
        prompt = load_prompt("scorer", RUBRIC_NAME.get(str(row.type), "rubric"), tier=None)
    except PromptNotFoundError:
        return None
    return AdminRubric(ref=prompt.ref, text=prompt.text, scored=False)


def session_setup(row: InterviewSession, card: Scorecard | None, consent: bool) -> SessionSetup:
    brief: InterviewerBrief | None = None
    if consent and row.brief_json:
        try:
            brief = InterviewerBrief.model_validate(row.brief_json)
        except ValueError:
            log.warning("brief of session %s does not validate", row.id, exc_info=True)
    return SessionSetup(brief=brief, rubric=rubric_for(row, card))
