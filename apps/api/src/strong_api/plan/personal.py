"""The personal plan (PS-1 to PS-5, ux-spec section 7). Rules in code, no model.

    GET /me/plan        the user's plan in their style, with Strova's next step for Home (HO-1)

One plan per user, computed on every read from the current state, so it never needs ticking:
- rehearsal items: one per interview of a live role, done at readiness 75 or more (RH-2). None
  before the first target role (PS-5);
- story items: one per story skill the interviews test, done when a Ready or Proven story shows
  it; one per started Draft ("Get X to Ready"); and the main resume's story ideas (RM-4);
- resume items: one per resume issue on the main resume (RM-5), done when accepted.

Order: rehearsals for the soonest interview date first, then by readiness; then story items;
then resume items. The first item not done is `next`.

Weekly style (PS-4): the week Monday to Saturday that holds today (Sunday shows the next week).
Done items fill the days before today, open items fill today onward, at most one per day.
Checklist style (PS-3): three groups with done and total counts and a status line naming the
group's next item.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.inputs.deps import CurrentUser, Db, Me
from strong_api.plan.interviews import (
    _live_roles,
    _role_interviews,
    _role_summary,
    _with_readiness,
    interview_competencies,
)
from strong_api.resume_checks.checks import check_resume
from strong_api.resume_checks.router import WHY, story_ideas
from strong_api.stories.router import display_status
from strong_core.db.models import Resume as ResumeRow
from strong_core.db.models import Story as StoryRow
from strong_core.db.models import User
from strong_core.profiles import resolve_profile
from strong_core.schemas import (
    READINESS_GOAL,
    Competency,
    InterviewType,
    Plan,
    PlanItem,
    PlanItemKind,
    PlanItemStatus,
    PlanStyle,
    Resume,
)

router = APIRouter(tags=["plan"])

TYPE_NAME: dict[InterviewType, str] = {
    InterviewType.BEHAVIORAL: "Behavioral",
    InterviewType.HIRING_MANAGER: "Hiring manager",
    InterviewType.TECHNICAL_QA: "Technical Q&A",
    InterviewType.CASE: "Case",
    InterviewType.RECRUITER_SCREEN: "Recruiter screen",
    InterviewType.CUSTOM: "Custom",
}
# Story items come from the skills that stories prove: the behavioral and hiring manager ones.
STORY_TYPES = (InterviewType.BEHAVIORAL, InterviewType.HIRING_MANAGER)
MAX_STORY_SKILLS = 6
MAX_IDEAS = 2
WEEK_DAYS = 6  # Monday to Saturday
GROUP_TITLE = {
    PlanItemKind.REHEARSAL: "Rehearsals",
    PlanItemKind.STORY: "Story completion",
    PlanItemKind.RESUME: "Resume gaps and issues",
}


def skill_name(c: Competency) -> str:
    return c.value.replace("_", " ").capitalize()


class PlanGroup(BaseModel):
    """PS-3: one checklist group."""

    kind: PlanItemKind
    title: str
    done: int
    total: int
    status: str = Field(description="One line naming the group's next item.")


class NextStep(BaseModel):
    """HO-1: Strova's next step on Home, from the plan's next item."""

    headline: str
    why: str | None = None
    action_label: str
    action_target: str
    role_label: str | None = Field(default=None, description="The ghost link to the role.")
    role_target: str | None = None


class PersonalPlan(BaseModel):
    """PS-1: the plan (core contract) with the checklist groups and the next step."""

    plan: Plan
    today: date
    week_end: date | None = Field(default=None, description="PS-4: the Saturday shown.")
    groups: list[PlanGroup] = Field(default_factory=list, description="PS-3: always all three.")
    next_key: str | None = None
    next_step: NextStep | None = None
    has_roles: bool = Field(description="PS-5: rehearsal items appear once a role is added.")


@dataclass
class _Item:
    item: PlanItem
    order: tuple[object, ...]
    deadline: date | None = None
    why: str | None = None
    role_label: str | None = None
    role_target: str | None = None


def week_start(today: date) -> date:
    """PS-4: the Monday of the week shown. On Sunday the plan shows the coming week."""
    if today.weekday() == 6:
        return today + timedelta(days=1)
    return today - timedelta(days=today.weekday())


def schedule(items: list[PlanItem], today: date) -> list[PlanItem]:
    """PS-4: at most one item per day, Monday to Saturday. Done items fill the days before
    today (latest done last), open items fill today onward, in plan order."""
    start = week_start(today)
    days = [start + timedelta(days=i) for i in range(WEEK_DAYS)]
    past = [d for d in days if d < today]
    ahead = [d for d in days if d >= today]
    done = [i for i in items if i.status == PlanItemStatus.DONE]
    open_ = [i for i in items if i.status != PlanItemStatus.DONE][: len(ahead)]
    shown_done = done[len(done) - len(past) :] if len(done) > len(past) else done
    done_days = past[len(past) - len(shown_done) :]
    out = [i.model_copy(update={"due": d}) for i, d in zip(shown_done, done_days, strict=True)]
    out += [i.model_copy(update={"due": d}) for i, d in zip(open_, ahead, strict=False)]
    return out


def groups(items: list[PlanItem]) -> list[PlanGroup]:
    out: list[PlanGroup] = []
    for kind in (PlanItemKind.REHEARSAL, PlanItemKind.STORY, PlanItemKind.RESUME):
        of = [i for i in items if i.kind == kind]
        done = sum(i.status == PlanItemStatus.DONE for i in of)
        nxt = next((i for i in of if i.status != PlanItemStatus.DONE), None)
        if not of:
            status = (
                "Added when you add a target role"
                if kind == PlanItemKind.REHEARSAL
                else "Nothing to do here yet"
            )
        elif nxt is None:
            status = "All done"
        else:
            status = f"Next: {nxt.title}" + (f", {nxt.sub}" if nxt.sub else "")
            status += f" · {len(of) - done} open"
        out.append(
            PlanGroup(kind=kind, title=GROUP_TITLE[kind], done=done, total=len(of), status=status)
        )
    return out


async def _rehearsal_items(
    db: AsyncSession, me: CurrentUser
) -> tuple[list[_Item], set[Competency], bool]:
    items: list[_Item] = []
    skills: list[Competency] = []
    roles = await _live_roles(db, me)
    for target in roles:
        profile = await resolve_profile(db, target.company_id)
        role = _role_summary(target, profile)
        company = role.company_name or role.name or "Your role"
        for row in await _role_interviews(db, target):
            summary, _ = await _with_readiness(db, row, profile, target)
            score = summary.readiness.score
            if row.interview_type in STORY_TYPES:
                skills += [c for c in interview_competencies(row) if c not in skills]
            done = score is not None and score >= READINESS_GOAL
            weakest = min(
                (c for c in summary.readiness.competencies if c.score is not None),
                key=lambda c: c.score or 0,
                default=None,
            )
            days = role.days_left
            why = None
            if weakest is not None and not done:
                why = f"Your weakest skill there is {skill_name(weakest.competency).lower()}."
            elif score is None:
                why = "Your first take sets your starting readiness."
            items.append(
                _Item(
                    PlanItem(
                        key=f"interview:{row.id}",
                        kind=PlanItemKind.REHEARSAL,
                        title=f"{company} · {TYPE_NAME[row.interview_type]}: readiness 75 or more",
                        sub="Not started" if score is None else f"Now {score}",
                        status=PlanItemStatus.DONE if done else PlanItemStatus.TODO,
                        action_label="Start the take" if score is None else "Retake",
                        action_target=f"/interviews/{row.id}",
                        target_id=row.id,
                    ),
                    order=(
                        role.interview_date is None or (days is not None and days < 0),
                        role.interview_date or date.max,
                        -1 if score is None else score,
                        row.created_at,
                    ),
                    deadline=role.interview_date if days is not None and days >= 0 else None,
                    why=why,
                    role_label=f"Open {company}",
                    role_target=f"/roles/{target.id}",
                )
            )
    items.sort(key=lambda i: i.order)
    return items, set(skills[: MAX_STORY_SKILLS * 2]), bool(roles)


async def _story_items(
    db: AsyncSession, me: CurrentUser, skills: set[Competency], main: ResumeRow | None
) -> list[_Item]:
    rows = list(
        await db.scalars(
            select(StoryRow)
            .where(StoryRow.org_id == me.org_id, StoryRow.user_id == me.user_id)
            .order_by(StoryRow.created_at, StoryRow.id)
        )
    )
    items: list[_Item] = []
    ordered = [c for c in Competency if c in skills][:MAX_STORY_SKILLS]
    for n, c in enumerate(ordered):
        showing = [r for r in rows if c.value in (r.skills or [])]
        ready = next((r for r in showing if display_status(r) != "draft"), None)
        draft = next((r for r in showing if display_status(r) == "draft"), None)
        label = "Proven" if ready is not None and display_status(ready) == "proven" else "Ready"
        if ready is not None:
            sub, target, action = ready.title, f"/stories/{ready.id}", None
        elif draft is not None:
            filled = sum(bool((getattr(draft, p) or "").strip()) for p in _PARTS)
            sub = f"“{draft.title}” has {filled} of 5 parts"
            target, action = f"/stories/{draft.id}/review", "Open"
        else:
            sub, target, action = "No story yet", f"/coach/new?skill={c.value}", "Craft with Strova"
        items.append(
            _Item(
                PlanItem(
                    key=f"skill:{c.value}",
                    kind=PlanItemKind.STORY,
                    title=f"{skill_name(c)}: a {label} story",
                    sub=sub,
                    status=PlanItemStatus.DONE if ready is not None else PlanItemStatus.TODO,
                    action_label=action,
                    action_target=target,
                    target_id=shown.id if (shown := ready or draft) is not None else None,
                ),
                order=(0, n),
                why=f"Your interviews test {skill_name(c).lower()}, and no story shows it yet."
                if ready is None
                else None,
            )
        )
    covered = {i.item.target_id for i in items}
    for n, r in enumerate(rows):
        if display_status(r) != "draft" or r.id in covered:
            continue
        filled = sum(bool((getattr(r, p) or "").strip()) for p in _PARTS)
        if filled == 0:
            continue  # an empty draft is not started
        items.append(
            _Item(
                PlanItem(
                    key=f"story:{r.id}",
                    kind=PlanItemKind.STORY,
                    title=f"Get “{r.title}” to Ready",
                    sub=f"{filled} of 5 parts written",
                    status=PlanItemStatus.TODO,
                    action_label="Open",
                    action_target=f"/stories/{r.id}/review",
                    target_id=r.id,
                ),
                order=(1, n),
                why="A Ready story has all five parts.",
            )
        )
    if main is not None and main.parsed_json is not None:
        # RM-4: the ideas the resume page lists (not a story yet, not dismissed).
        ideas = (await story_ideas(main.id, db, me)).ideas[:MAX_IDEAS]
        for n, idea in enumerate(ideas):
            items.append(
                _Item(
                    PlanItem(
                        key=f"idea:{main.id}:{idea.resume_line_ref}",
                        kind=PlanItemKind.STORY,
                        title=f"Build a story from “{idea.achievement}”",
                        sub="A story idea from your resume",
                        status=PlanItemStatus.TODO,
                        action_label="Build on it",
                        action_target=f"/coach/new?resume={main.id}&idea={idea.resume_line_ref}",
                        target_id=main.id,
                    ),
                    order=(2, n),
                    why="It is on your resume, and no story tells it yet.",
                )
            )
    return items


_PARTS = ("context", "stakes", "action", "result", "reflection")


async def _main_resume(db: AsyncSession, me: CurrentUser) -> ResumeRow | None:
    row: ResumeRow | None = await db.scalar(
        select(ResumeRow)
        .where(
            ResumeRow.org_id == me.org_id,
            ResumeRow.user_id == me.user_id,
            ResumeRow.deleted_at.is_(None),
            ResumeRow.parsed_json.is_not(None),
        )
        .order_by(ResumeRow.is_main.desc(), ResumeRow.uploaded_at.desc())
        .limit(1)
    )
    return row


def _resume_items(main: ResumeRow | None, today: date) -> list[_Item]:
    if main is None or main.parsed_json is None:
        return []
    resume = Resume.model_validate(main.parsed_json)
    accepted = {str(i.get("key", "")).partition(WHY)[0] for i in main.accepted_issues or []}
    items: list[_Item] = []
    for n, issue in enumerate(check_resume(resume, today=today.strftime("%Y-%m"))):
        done = issue.key in accepted
        items.append(
            _Item(
                PlanItem(
                    key=f"issue:{issue.key}"[:200],
                    kind=PlanItemKind.RESUME,
                    title=issue.title,
                    sub=None if done else issue.detail,
                    status=PlanItemStatus.DONE if done else PlanItemStatus.TODO,
                    action_label=None if done else "Fix",
                    action_target=f"/resumes/{main.id}",
                    target_id=main.id,
                ),
                order=(n,),
                why=issue.why,
            )
        )
    return items


def _headline(first: _Item) -> NextStep:
    item = first.item
    if item.kind == PlanItemKind.REHEARSAL:
        what = item.title.split(":")[0]
        if first.deadline is not None:
            days = (first.deadline - datetime.now(UTC).date()).days
            when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
            headline = f"Your {what.split(' · ')[0]} interview is {when}. Rehearse {what}."
        else:
            headline = f"Rehearse {what}. {item.sub or ''}".strip()
            if item.sub and item.sub.startswith("Now"):
                headline = f"Rehearse {what}: readiness {item.sub[4:]} of 75."
    elif item.kind == PlanItemKind.STORY:
        headline = (
            item.title
            if item.title.startswith(("Get", "Build"))
            else f"Get {item.title[0].lower()}{item.title[1:]}."
        )
        headline = headline.rstrip(".") + "."
    else:
        headline = f"Fix your resume: {item.title[0].lower()}{item.title[1:]}".rstrip(".") + "."
    return NextStep(
        headline=headline,
        why=first.why,
        action_label=item.action_label or "Open",
        action_target=item.action_target or "/",
        role_label=first.role_label,
        role_target=first.role_target,
    )


async def build_plan(
    db: AsyncSession, me: CurrentUser, style: PlanStyle, today: date | None = None
) -> PersonalPlan:
    today = today or datetime.now(UTC).date()
    rehearsals, skills, has_roles = await _rehearsal_items(db, me)
    main = await _main_resume(db, me)
    stories = await _story_items(db, me, skills, main)
    resume = _resume_items(main, today)
    ordered = [*rehearsals, *stories, *resume]
    first = next((i for i in ordered if i.item.status != PlanItemStatus.DONE), None)
    items = [
        i.item.model_copy(update={"status": PlanItemStatus.NEXT}) if i is first else i.item
        for i in ordered
    ]
    week = None
    week_end = None
    if style == PlanStyle.WEEKLY:
        items = schedule(items, today)
        week = week_start(today)
        week_end = week + timedelta(days=WEEK_DAYS - 1)
    return PersonalPlan(
        plan=Plan(style=style, week_start=week, items=items),
        today=today,
        week_end=week_end,
        groups=groups([i.item for i in ordered]),
        next_key=first.item.key if first else None,
        next_step=_headline(first) if first else None,
        has_roles=has_roles,
    )


async def plan_for(db: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID) -> PersonalPlan:
    user = await db.get(User, user_id)
    style = (user.plan_style if user else None) or PlanStyle.WEEKLY
    return await build_plan(db, CurrentUser(user_id=user_id, org_id=org_id), style)


def plan_line(plan: PersonalPlan) -> str | None:
    """DB-6: the debrief's "Your plan updated: next is …" text, from the plan's next item."""
    item = next((i for i in plan.plan.items if i.key == plan.next_key), None)
    if item is None:
        return None
    when = ""
    if item.due is not None:
        when = " today" if item.due == plan.today else f" on {item.due.strftime('%A')}"
    return f"{item.title}{when}."


@router.get("/me/plan")
async def get_my_plan(db: Db, me: Me) -> PersonalPlan:
    """PS-1: the user's plan in their style (weekly until chosen), with Home's next step."""
    return await plan_for(db, me.user_id, me.org_id)
