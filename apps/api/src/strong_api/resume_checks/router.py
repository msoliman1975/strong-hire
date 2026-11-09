"""Resume issues (RM-5) and story ideas (RM-4) for the resume page and onboarding.

GET /resumes/{id}/issues runs the rule-based check (the same rules as the web check) and splits
the issues into open and accepted ones, using the keys stored by PUT .../accepted-issues.

GET /resumes/{id}/story-ideas lists one idea per achievement that no story uses and the user has
not dismissed, with the likely skills once the worker job has added them. POST
.../story-ideas/dismiss stores "Not a story" as a dismissed story_idea suggestion.

GET /story-ideas/counts gives the open and used counts of every resume in one read, for the
Resumes list (RSD-16), with the same rules as the per-resume list.

GET /stories/recommendations is the Recommended rows of Career Stories (CS-5): the resume ideas
pooled across every resume (CS-1 to CS-4) and the open missing-skill suggestions of the user's
target roles (CS-11). It lives here, not in the stories router, because the stories router's
/stories/{id} would catch the path.

All of them use the pool (strong_api.resume_checks.pool): an achievement used, quoted or
dismissed on one resume version is used or dismissed on every version (CS-3).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from strong_api.inputs.deps import Db, Me
from strong_api.resume_checks.checks import ResumeIssue, check_resume
from strong_api.resume_checks.pool import IdeaPool, build_pool
from strong_api.resume_checks.story_ideas import (
    Achievement,
    achievements,
    idea_reason,
    missing_parts,
    normalize,
)
from strong_core.db.models import JobTarget, Story
from strong_core.db.models import Resume as ResumeRow
from strong_core.db.models import Suggestion as SuggestionRow
from strong_core.schemas import (
    Competency,
    JobPosting,
    MissingSkillPayload,
    Resume,
    StoryIdeaPayload,
    StoryPart,
    SuggestionKind,
    SuggestionStatus,
)

router = APIRouter(tags=["resume checks"])

WHY = "|why="
"""An issue accepted with a reason is stored as `<key>|why=<reason>` (the web's format)."""


class AcceptedResumeIssue(ResumeIssue):
    accepted_at: datetime
    reason: str | None = Field(default=None, description="The reason it was accepted with.")


class ResumeIssues(BaseModel):
    """RM-5: the check's issues for one resume, in the web check's shape."""

    open: list[ResumeIssue]
    accepted: list[AcceptedResumeIssue]
    job_target_id: uuid.UUID | None = Field(
        default=None, description="Set when the job-mode check (must-haves) ran."
    )


class StoryIdeaOut(BaseModel):
    achievement: str
    role: str
    resume_line_ref: str
    skills: list[Competency] = Field(description="Likely skills. Empty until the job adds them.")
    missing_parts: list[StoryPart]


class UsedAchievement(BaseModel):
    achievement: str
    resume_line_ref: str
    story_id: uuid.UUID
    story_title: str


class StoryIdeasOut(BaseModel):
    """RM-4: ideas from the resume, and the achievements a story already uses (they link to it)."""

    ideas: list[StoryIdeaOut]
    used: list[UsedAchievement]
    skills: Literal["ready", "pending"] = Field(
        description="ready: the skills job ran for every idea it knows; pending otherwise."
    )


class DismissIdea(BaseModel):
    resume_line_ref: str = Field(
        pattern=r"^roles\[\d+\]\.achievements\[\d+\]$",
        description="The achievement, as roles[<i>].achievements[<j>] in the parsed resume.",
    )


async def _read_resume(db: Db, me: Me, resume_id: uuid.UUID) -> tuple[ResumeRow, Resume]:
    row = await db.scalar(
        select(ResumeRow).where(
            ResumeRow.id == resume_id,
            ResumeRow.org_id == me.org_id,
            ResumeRow.user_id == me.user_id,
            ResumeRow.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found")
    if row.parsed_json is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The resume is still being read. Try again in a minute."
        )
    return row, Resume.model_validate(row.parsed_json)


@router.get("/resumes/{resume_id}/issues")
async def resume_issues(
    resume_id: uuid.UUID, db: Db, me: Me, job_target_id: uuid.UUID | None = None
) -> ResumeIssues:
    """RM-5: open and accepted issues. With `job_target_id`, also the must-haves the resume
    never shows (IN-12 job mode)."""
    row, resume = await _read_resume(db, me, resume_id)
    job = None
    if job_target_id is not None:
        target = await db.scalar(
            select(JobTarget).where(
                JobTarget.id == job_target_id,
                JobTarget.org_id == me.org_id,
                JobTarget.user_id == me.user_id,
                JobTarget.deleted_at.is_(None),
            )
        )
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Job target not found")
        if target.parsed_json is not None:
            job = JobPosting.model_validate(target.parsed_json)
    today = datetime.now(UTC).strftime("%Y-%m")
    stored = {}
    for item in row.accepted_issues or []:
        key = str(item.get("key", ""))
        base, _, reason = key.partition(WHY)
        stored[base] = (item, reason or None)
    open_issues: list[ResumeIssue] = []
    accepted: list[AcceptedResumeIssue] = []
    for issue in check_resume(resume, today=today, job=job):
        found = stored.get(issue.key)
        if found is None:
            open_issues.append(issue)
        else:
            accepted.append(
                AcceptedResumeIssue(
                    **issue.model_dump(),
                    accepted_at=datetime.fromisoformat(str(found[0]["accepted_at"])),
                    reason=found[1],
                )
            )
    return ResumeIssues(
        open=open_issues, accepted=accepted, job_target_id=job_target_id if job else None
    )


def _ideas_for(pool: IdeaPool, row: ResumeRow, resume: Resume) -> StoryIdeasOut:
    """RM-4: one idea per achievement no story uses, not dismissed, with likely skills. CS-3:
    used and dismissed are judged across every resume version."""
    ideas: list[StoryIdeaOut] = []
    used: list[UsedAchievement] = []
    pending = False
    for item in achievements(resume):
        group = pool.group_of(row.id, item.ref)
        if group is None:
            continue
        if group.story is not None:
            used.append(
                UsedAchievement(
                    achievement=item.text,
                    resume_line_ref=item.ref,
                    story_id=group.story.id,
                    story_title=group.story.title,
                )
            )
            continue
        if group.dismissed:
            continue
        pending = pending or any(
            line.suggestion is None for line in group.lines if line.resume_id == row.id
        )
        ideas.append(
            StoryIdeaOut(
                achievement=item.text,
                role=item.role,
                resume_line_ref=item.ref,
                skills=group.skills,
                missing_parts=missing_parts(item.text),
            )
        )
    return StoryIdeasOut(ideas=ideas, used=used, skills="pending" if pending else "ready")


async def _pool(db: Db, me: Me) -> IdeaPool:
    """CS-1: every readable resume of the user, every story_idea suggestion (deleted resumes
    too) and every story that is not deleted (an archived story still tells its idea)."""
    resumes = await db.scalars(
        select(ResumeRow).where(
            ResumeRow.org_id == me.org_id,
            ResumeRow.user_id == me.user_id,
            ResumeRow.deleted_at.is_(None),
            ResumeRow.parsed_json.is_not(None),
        )
    )
    suggestions = await db.scalars(
        select(SuggestionRow).where(
            SuggestionRow.org_id == me.org_id,
            SuggestionRow.user_id == me.user_id,
            SuggestionRow.kind == SuggestionKind.STORY_IDEA,
        )
    )
    stories = await db.scalars(
        select(Story).where(Story.org_id == me.org_id, Story.user_id == me.user_id, Story.live())
    )
    return build_pool(list(resumes), list(suggestions), list(stories))


@router.get("/resumes/{resume_id}/story-ideas")
async def story_ideas(resume_id: uuid.UUID, db: Db, me: Me) -> StoryIdeasOut:
    """RM-4: one idea per achievement no story uses, not dismissed, with likely skills."""
    row, resume = await _read_resume(db, me, resume_id)
    return _ideas_for(await _pool(db, me), row, resume)


class RecommendedIdea(BaseModel):
    """CS-1, CS-4: one resume achievement, however many resumes it is on."""

    kind: Literal["resume_idea"] = "resume_idea"
    achievement: str = Field(description="The line as the newest resume words it.")
    role: str
    resume_id: uuid.UUID = Field(description="The newest resume with the line: Start uses it.")
    resume_line_ref: str
    resumes: int = Field(ge=1, description="How many resumes have the line (From 2 resumes).")
    skills: list[Competency]
    missing_parts: list[StoryPart]


class RecommendedSkill(BaseModel):
    """CS-11: a skill one of the user's target roles tests that no story covers."""

    kind: Literal["missing_skill"] = "missing_skill"
    suggestion_id: uuid.UUID
    competency: Competency
    job_target_id: uuid.UUID
    company: str | None
    job_title: str | None
    reason: str


class StoryRecommendations(BaseModel):
    """CS-5: the Recommended rows of Career Stories."""

    skills: list[RecommendedSkill] = Field(description="Job gaps first (CS-5 sort order).")
    ideas: list[RecommendedIdea] = Field(description="Newest resume first, in resume order.")


@router.get("/stories/recommendations")
async def story_recommendations(db: Db, me: Me) -> StoryRecommendations:
    """CS-1 to CS-5, CS-11: the stories Strova recommends writing, without duplicates."""
    pool = await _pool(db, me)
    ideas = [
        RecommendedIdea(
            achievement=g.newest.item.text,
            role=g.newest.item.role,
            resume_id=g.newest.resume_id,
            resume_line_ref=g.newest.item.ref,
            resumes=len(g.resume_ids),
            skills=g.skills,
            missing_parts=missing_parts(g.newest.item.text),
        )
        for g in pool.groups
        if g.lines and g.story is None and not g.dismissed
    ]
    rows = await db.execute(
        select(SuggestionRow, JobTarget)
        .join(JobTarget, JobTarget.id == SuggestionRow.job_target_id)
        .where(
            SuggestionRow.org_id == me.org_id,
            SuggestionRow.user_id == me.user_id,
            SuggestionRow.kind == SuggestionKind.MISSING_SKILL,
            SuggestionRow.status == SuggestionStatus.OPEN,
            JobTarget.deleted_at.is_(None),
            JobTarget.archived_at.is_(None),
        )
        .order_by(SuggestionRow.created_at.desc(), SuggestionRow.id)
    )
    skills: list[RecommendedSkill] = []
    seen: set[tuple[Competency, uuid.UUID]] = set()
    for suggestion, target in rows.tuples():
        payload = MissingSkillPayload.model_validate(suggestion.payload)
        key = (payload.competency, target.id)
        if key in seen:
            continue
        seen.add(key)
        posting = (
            JobPosting.model_validate(target.parsed_json)
            if target.parsed_json is not None
            else None
        )
        skills.append(
            RecommendedSkill(
                suggestion_id=suggestion.id,
                competency=payload.competency,
                job_target_id=target.id,
                company=posting.company_name if posting else None,
                job_title=posting.title if posting else target.name,
                reason=suggestion.reason,
            )
        )
    return StoryRecommendations(skills=skills, ideas=ideas)


class StoryIdeaCount(BaseModel):
    """RSD-16: one resume's story ideas, counted with the rules of GET .../story-ideas."""

    resume_id: uuid.UUID
    ideas: int = Field(description="Open ideas: not used by a story and not dismissed.")
    used: int = Field(description="Achievements a story already tells.")


@router.get("/story-ideas/counts")
async def story_idea_counts(db: Db, me: Me) -> list[StoryIdeaCount]:
    """RSD-16: the story-idea counts of every resume that has been read, in one request."""
    rows = list(
        await db.scalars(
            select(ResumeRow).where(
                ResumeRow.org_id == me.org_id,
                ResumeRow.user_id == me.user_id,
                ResumeRow.deleted_at.is_(None),
                ResumeRow.parsed_json.is_not(None),
            )
        )
    )
    pool = await _pool(db, me)
    out: list[StoryIdeaCount] = []
    for row in rows:
        found = _ideas_for(pool, row, Resume.model_validate(row.parsed_json))
        out.append(StoryIdeaCount(resume_id=row.id, ideas=len(found.ideas), used=len(found.used)))
    return out


def _achievement_at(resume: Resume, ref: str) -> Achievement:
    found = next((a for a in achievements(resume) if a.ref == ref), None)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No achievement at that place")
    return found


@router.post("/resumes/{resume_id}/story-ideas/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_story_idea(resume_id: uuid.UUID, body: DismissIdea, db: Db, me: Me) -> None:
    """RM-4, SG-8: "Not a story". The idea is stored as a dismissed suggestion and does not come
    back, even after the skills job runs again. Safe to repeat."""
    row, resume = await _read_resume(db, me, resume_id)
    item = _achievement_at(resume, body.resume_line_ref)
    key = normalize(item.text)
    existing = next(
        (
            s
            for s in await db.scalars(
                select(SuggestionRow).where(
                    SuggestionRow.org_id == me.org_id,
                    SuggestionRow.user_id == me.user_id,
                    SuggestionRow.source_resume_id == row.id,
                    SuggestionRow.kind == SuggestionKind.STORY_IDEA,
                )
            )
            if normalize(str(s.payload.get("achievement", ""))) == key
        ),
        None,
    )
    now = datetime.now(UTC)
    if existing is None:
        db.add(
            SuggestionRow(
                org_id=me.org_id,
                user_id=me.user_id,
                kind=SuggestionKind.STORY_IDEA,
                status=SuggestionStatus.DISMISSED,
                source_resume_id=row.id,
                resume_id=row.id,
                payload=StoryIdeaPayload(
                    achievement=item.text,
                    role=item.role,
                    resume_line_ref=item.ref,
                    missing_parts=missing_parts(item.text),
                ).model_dump(mode="json"),
                reason=idea_reason(item),
                resolved_at=now,
            )
        )
    elif existing.status != SuggestionStatus.DISMISSED:
        existing.status = SuggestionStatus.DISMISSED
        existing.resolved_at = now
    await db.commit()
