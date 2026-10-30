"""Resume issues (RM-5) and story ideas (RM-4) for the resume page and onboarding.

GET /resumes/{id}/issues runs the rule-based check (the same rules as the web check) and splits
the issues into open and accepted ones, using the keys stored by PUT .../accepted-issues.

GET /resumes/{id}/story-ideas lists one idea per achievement that no story uses and the user has
not dismissed, with the likely skills once the worker job has added them. POST
.../story-ideas/dismiss stores "Not a story" as a dismissed story_idea suggestion.
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


def _story_texts(story: Story) -> str:
    return normalize(
        " ".join(
            p or ""
            for p in (story.context, story.stakes, story.action, story.result, story.reflection)
        )
    )


@router.get("/resumes/{resume_id}/story-ideas")
async def story_ideas(resume_id: uuid.UUID, db: Db, me: Me) -> StoryIdeasOut:
    """RM-4: one idea per achievement no story uses, not dismissed, with likely skills."""
    row, resume = await _read_resume(db, me, resume_id)
    suggestions = {
        normalize(str(s.payload.get("achievement", ""))): s
        for s in await db.scalars(
            select(SuggestionRow).where(
                SuggestionRow.org_id == me.org_id,
                SuggestionRow.user_id == me.user_id,
                SuggestionRow.source_resume_id == row.id,
                SuggestionRow.kind == SuggestionKind.STORY_IDEA,
            )
        )
    }
    stories = list(
        await db.scalars(
            select(Story).where(Story.org_id == me.org_id, Story.user_id == me.user_id)
        )
    )
    by_id = {s.id: s for s in stories}
    texts = [(s, _story_texts(s)) for s in stories]
    ideas: list[StoryIdeaOut] = []
    used: list[UsedAchievement] = []
    for item in achievements(resume):
        key = normalize(item.text)
        suggestion = suggestions.get(key)
        # Used: a story crafted from this idea, or a story whose parts quote the line.
        story = by_id.get(suggestion.story_id) if suggestion and suggestion.story_id else None
        story = story or next((s for s, t in texts if key and key in t), None)
        if story is not None:
            used.append(
                UsedAchievement(
                    achievement=item.text,
                    resume_line_ref=item.ref,
                    story_id=story.id,
                    story_title=story.title,
                )
            )
            continue
        if suggestion is not None and suggestion.status == SuggestionStatus.DISMISSED:
            continue
        skills = StoryIdeaPayload.model_validate(suggestion.payload).skills if suggestion else []
        ideas.append(
            StoryIdeaOut(
                achievement=item.text,
                role=item.role,
                resume_line_ref=item.ref,
                skills=skills,
                missing_parts=missing_parts(item.text),
            )
        )
    pending = any(normalize(i.achievement) not in suggestions for i in ideas)
    return StoryIdeasOut(ideas=ideas, used=used, skills="pending" if pending else "ready")


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
