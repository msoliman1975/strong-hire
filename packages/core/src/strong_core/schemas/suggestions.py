"""Suggestions from Strova (SG-1 to SG-8), story ideas (RM-4) and story reviews (ST-11).

One suggestion model, with one payload contract per kind. The payload's `kind` must match the
suggestion's `kind`. Every proposed text comes only from the user's own words (CO-9, SG-7), so
model-written payloads carry the quotes they came from.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from strong_core.schemas.base import Contract
from strong_core.schemas.enums import Competency, StoryPart, SuggestionKind, SuggestionStatus
from strong_core.schemas.stories import STORY_TITLE_MAX_CHARS


def _unique(values: list[Competency] | list[StoryPart], name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{name} must not repeat")


class StoryPartEdit(Contract):
    """SG-2, ST-11: a before-and-after edit of one story part."""

    part: StoryPart
    before: str | None = Field(description="The part as it is now. Null when it is empty.")
    after: str = Field(min_length=1, description="The proposed text.")
    quotes: list[str] = Field(
        default_factory=list, description="The user's words the new text came from, verbatim."
    )


class TuneStoryPayload(Contract):
    """SG-2: tune one part of a story from a debrief answer that used it."""

    kind: Literal["tune_story"] = "tune_story"
    edit: StoryPartEdit


class NewStoryPayload(Contract):
    """SG-3: a new story from a strong answer that matches no story."""

    kind: Literal["new_story"] = "new_story"
    title: str = Field(min_length=1, max_length=STORY_TITLE_MAX_CHARS)
    context: str | None = None
    stakes: str | None = None
    action: str | None = None
    result: str | None = None
    reflection: str | None = None
    skills: list[Competency] = Field(default_factory=list)
    quotes: list[str] = Field(
        default_factory=list, description="The answer's words the parts came from, verbatim."
    )

    @model_validator(mode="after")
    def _check(self) -> NewStoryPayload:
        _unique(self.skills, "skills")
        if not any(getattr(self, p.value) for p in StoryPart):
            raise ValueError("a new story needs at least one part")
        return self


class MissingSkillPayload(Contract):
    """SG-4: a tested skill with no story; accepting opens crafting aimed at it."""

    kind: Literal["missing_skill"] = "missing_skill"
    competency: Competency = Field(description="The target skill for crafting.")


class TailorRolePayload(Contract):
    """SG-5: the lead story for a skill at one company and one detail to bring forward."""

    kind: Literal["tailor_role"] = "tailor_role"
    company: str = Field(min_length=1, description="Shown as the note title: For {company}.")
    competency: Competency | None = Field(
        default=None, description="The skill this story leads for at the company."
    )
    note: str = Field(min_length=1, description="The detail to bring forward.")


class ResumeLineEdit(Contract):
    """SG-6: a rewrite of one resume line from a story's words."""

    resume_line_ref: str = Field(
        min_length=1,
        description="Where the line is in schemas.Resume, as roles[<i>].achievements[<j>].",
        pattern=r"^roles\[\d+\]\.achievements\[\d+\]$",
    )
    before: str = Field(min_length=1)
    after: str = Field(min_length=1)
    quotes: list[str] = Field(
        default_factory=list, description="The story's words the rewrite came from, verbatim."
    )


class ImproveResumeLinePayload(ResumeLineEdit):
    """SG-6: the payload of an improve resume line suggestion."""

    kind: Literal["improve_resume_line"] = "improve_resume_line"


class StoryIdea(Contract):
    """RM-4: one resume achievement not used by a story, as a seed for crafting."""

    achievement: str = Field(min_length=1, description="The resume line, verbatim.")
    role: str | None = Field(default=None, description="The role it is under: title, company.")
    resume_line_ref: str | None = Field(
        default=None,
        description="Where the line is in schemas.Resume, as roles[<i>].achievements[<j>].",
        pattern=r"^roles\[\d+\]\.achievements\[\d+\]$",
    )
    skills: list[Competency] = Field(
        default_factory=list, description="Likely skills. Empty when the worker call failed."
    )
    missing_parts: list[StoryPart] = Field(
        default_factory=list, description="Story parts the line does not give."
    )

    @model_validator(mode="after")
    def _check(self) -> StoryIdea:
        _unique(self.skills, "skills")
        _unique(self.missing_parts, "missing_parts")
        return self


class StoryIdeas(Contract):
    """RM-4: the likely skills for a resume's achievements, one worker call per resume."""

    items: list[StoryIdea] = Field(default_factory=list)


class StoryIdeaPayload(StoryIdea):
    """RM-4: the payload of a story idea suggestion."""

    kind: Literal["story_idea"] = "story_idea"


class StoryReviewNote(Contract):
    """ST-11: Strova's note on one story part, with an optional edit from the user's words."""

    part: StoryPart
    note: str = Field(min_length=1)
    edit: StoryPartEdit | None = None

    @model_validator(mode="after")
    def _edit_matches_part(self) -> StoryReviewNote:
        if self.edit is not None and self.edit.part != self.part:
            raise ValueError("edit.part must match part")
        return self


class StoryReview(Contract):
    """ST-11: per-part notes and before-and-after edits for one story."""

    summary: str = Field(min_length=1, description="One or two sentences from Strova.")
    notes: list[StoryReviewNote] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_note_per_part(self) -> StoryReview:
        _unique([n.part for n in self.notes], "notes")
        return self


class ReviewPayload(Contract):
    """ST-11: the payload of a review suggestion."""

    kind: Literal["review"] = "review"
    review: StoryReview


SuggestionPayload = Annotated[
    TuneStoryPayload
    | NewStoryPayload
    | MissingSkillPayload
    | TailorRolePayload
    | ImproveResumeLinePayload
    | StoryIdeaPayload
    | ReviewPayload,
    Field(discriminator="kind"),
]


class Suggestion(Contract):
    """SG-1: one suggestion from Strova. The suggestions table holds org_id and user_id."""

    id: UUID
    kind: SuggestionKind
    status: SuggestionStatus = SuggestionStatus.OPEN
    payload: SuggestionPayload
    reason: str = Field(min_length=1, description="Why Strova suggests it, one sentence.")
    source_session_id: UUID | None = Field(default=None, description="The debrief's session.")
    source_question_ref: str | None = Field(
        default=None, description="QuestionScore.question_ref of the answer."
    )
    source_resume_id: UUID | None = Field(default=None, description="The resume it came from.")
    job_target_id: UUID | None = Field(default=None, description="The role it is for.")
    story_id: UUID | None = Field(default=None, description="The story it changes.")
    resume_id: UUID | None = Field(default=None, description="The resume it changes.")
    prompt_ref: str | None = Field(
        default=None, description="The prompt that wrote it. Null for rule-based suggestions."
    )
    created_at: datetime
    resolved_at: datetime | None = Field(
        default=None, description="When it was accepted or dismissed."
    )

    @model_validator(mode="after")
    def _check(self) -> Suggestion:
        if self.payload.kind != self.kind.value:
            raise ValueError("payload.kind must match kind")
        if (self.status == SuggestionStatus.OPEN) != (self.resolved_at is None):
            raise ValueError("resolved_at is null exactly when status is open")
        return self


class StoryAnswer(Contract):
    """ST-13: Strova's answer to a question asked on Career Stories, from the user's own stories
    and roles. The stories it leans on are named, so the screen can link them."""

    answer: str = Field(min_length=1, description="Two to four sentences, spoken to the user.")
    story_ids: list[UUID] = Field(
        default_factory=list, description="The user's stories the answer is about, best first."
    )
    quotes: list[str] = Field(
        default_factory=list,
        description="The user's words the answer's facts came from, verbatim (CO-9).",
    )
