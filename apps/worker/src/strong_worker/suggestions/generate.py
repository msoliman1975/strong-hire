"""The coach-role calls that write suggestions (SG-2, SG-3, SG-5, SG-6, ST-11).

Each call uses a `coach/suggest_*` or `coach/review` prompt and a contract from
strong_core.schemas.suggestions. Code then owns what it can: the part's current text ("before"),
the resume line's place and text, the company. Texts that must be the user's words pass
`facts.unbacked`; on a miss the coach is asked once more with the problems (prompt
coach/suggest_fix), and a second miss returns None, so nothing is stored.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel

from strong_core.gateway import Message, ModelGateway, Role
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    Competency,
    NewStoryPayload,
    ResumeLineEdit,
    Story,
    StoryPart,
    StoryPartEdit,
    StoryReview,
    StoryReviewNote,
    TailorRolePayload,
)
from strong_worker.quoting import quote_untrusted
from strong_worker.scoring.stories import render_story
from strong_worker.suggestions.facts import numbers, said_text, unbacked

log = logging.getLogger(__name__)

ROLE = Role.COACH
ANSWER_CHARS = 6000
# SG-3: an answer that scores 3 needs these parts to become a story; a 4 needs none.
STORY_PARTS_NEEDED = (StoryPart.CONTEXT, StoryPart.ACTION, StoryPart.RESULT)


@dataclass
class Written[T: BaseModel]:
    output: T | None
    prompt_ref: str | None = None
    last: T | None = None
    """The last reply, also when it failed the check."""
    problems: list[str] = field(default_factory=list)
    calls: int = 0


async def _complete_checked[T: BaseModel](
    gateway: ModelGateway,
    messages: list[Message],
    output_type: type[T],
    check: Callable[[T], list[str]],
) -> Written[T]:
    refs: list[str] = []
    problems: list[str] = []
    last: T | None = None
    for attempt in (1, 2):
        done = await gateway.complete(ROLE, messages, output_type=output_type)
        refs += done.prompt_refs
        last = done.output
        problems = check(last)
        if not problems:
            return Written(last, ",".join(dict.fromkeys(refs)), last, [], attempt)
        log.info("suggestion rejected (attempt %d): %s", attempt, "; ".join(problems))
        messages = [
            *messages,
            Message(role="assistant", content=done.output.model_dump_json()),
            load_prompt(ROLE, "suggest_fix").message(
                "user", problems="\n".join(f"- {p}" for p in problems)
            ),
        ]
    return Written(None, ",".join(dict.fromkeys(refs)), last, problems, 2)


def _clip(text: str, limit: int = ANSWER_CHARS) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit]


def story_words(story: Story) -> list[str]:
    """The user's own words in a story: its title and parts."""
    return [story.title, *(story.part(p) or "" for p in StoryPart)]


# --- SG-2: tune a story ------------------------------------------------------------------------


def check_tune(edit: StoryPartEdit, said: str) -> list[str]:
    return unbacked(edit.after, edit.quotes, said)


async def tune_story(
    gateway: ModelGateway, story: Story, answer: str, fix: str
) -> Written[StoryPartEdit]:
    said = said_text([answer])
    messages = [
        load_prompt(ROLE, "suggest_tune").message("system"),
        load_prompt(ROLE, "suggest_tune_input").message(
            "user",
            story=render_story("Story", story),
            fix=quote_untrusted(fix),
            answer=_clip(answer),
        ),
    ]
    written = await _complete_checked(
        gateway, messages, StoryPartEdit, lambda e: check_tune(e, said)
    )
    if written.output is not None:
        before = story.part(written.output.part)
        if (before or "").strip() == written.output.after.strip():
            return Written(None, written.prompt_ref, None, ["no change"], written.calls)
        written.output = written.output.model_copy(update={"before": before or None})
    return written


# --- SG-3: new story ---------------------------------------------------------------------------


def check_new_story(payload: NewStoryPayload, said: str) -> list[str]:
    problems: list[str] = []
    for part in StoryPart:
        text = getattr(payload, part.value)
        if text:
            problems += [f"{part.value}: {p}" for p in unbacked(text, payload.quotes, said)]
    return problems


def has_story_parts(payload: NewStoryPayload) -> bool:
    return all(getattr(payload, p.value) for p in STORY_PARTS_NEEDED)


async def new_story(
    gateway: ModelGateway, question: str, answer: str, skills: Sequence[Competency]
) -> Written[NewStoryPayload]:
    said = said_text([answer])
    messages = [
        load_prompt(ROLE, "suggest_new_story").message(
            "system", skills=", ".join(c.value for c in Competency)
        ),
        load_prompt(ROLE, "suggest_new_story_input").message(
            "user", question=quote_untrusted(question), answer=_clip(answer)
        ),
    ]
    written = await _complete_checked(
        gateway, messages, NewStoryPayload, lambda p: check_new_story(p, said)
    )
    if written.output is not None and not written.output.skills and skills:
        written.output = written.output.model_copy(update={"skills": list(dict.fromkeys(skills))})
    return written


# --- SG-5: tailor for a role -------------------------------------------------------------------


def check_tailor(payload: TailorRolePayload, story: Story) -> list[str]:
    """A tailoring note names a detail of the story: its numbers must be the story's."""
    said = said_text(story_words(story))
    return [f"number not in the story: {n}" for n in numbers(payload.note) if n not in said]


async def tailor_role(
    gateway: ModelGateway, story: Story, job: str, company: str, competency: Competency
) -> Written[TailorRolePayload]:
    messages = [
        load_prompt(ROLE, "suggest_tailor").message("system"),
        load_prompt(ROLE, "suggest_tailor_input").message(
            "user",
            job=quote_untrusted(job),
            competency=competency.value,
            story=render_story("Story", story),
        ),
    ]
    written = await _complete_checked(
        gateway, messages, TailorRolePayload, lambda p: check_tailor(p, story)
    )
    if written.output is not None:
        written.output = written.output.model_copy(
            update={"company": company, "competency": competency}
        )
    return written


# --- SG-6: improve a resume line ---------------------------------------------------------------


def check_resume_line(edit: ResumeLineEdit, said: str) -> list[str]:
    return unbacked(edit.after, edit.quotes, said)


async def improve_resume_line(
    gateway: ModelGateway, story: Story, ref: str, line: str
) -> Written[ResumeLineEdit]:
    said = said_text([*story_words(story), line])
    messages = [
        load_prompt(ROLE, "suggest_resume_line").message("system"),
        load_prompt(ROLE, "suggest_resume_line_input").message(
            "user", ref=ref, line=quote_untrusted(line), story=render_story("Story", story)
        ),
    ]
    written = await _complete_checked(
        gateway, messages, ResumeLineEdit, lambda e: check_resume_line(e, said)
    )
    if written.output is not None:
        written.output = written.output.model_copy(update={"resume_line_ref": ref, "before": line})
    return written


# --- ST-11: review a story ---------------------------------------------------------------------


def check_review(review: StoryReview, said: str) -> list[str]:
    return [
        f"{n.part.value}: {p}"
        for n in review.notes
        if n.edit is not None
        for p in unbacked(n.edit.after, n.edit.quotes, said)
    ]


async def review_story(
    gateway: ModelGateway, story: Story, said_texts: Sequence[str]
) -> Written[StoryReview]:
    """ST-11: the review. An edit that is not the user's words is dropped after the second try;
    its note stays."""
    words = [*story_words(story), *said_texts]
    said = said_text(words)
    messages = [
        load_prompt(ROLE, "review").message("system"),
        load_prompt(ROLE, "review_input").message(
            "user",
            story=render_story("Story", story),
            said="\n\n".join(_clip(t, 2000) for t in words if t) or "(nothing yet)",
        ),
    ]
    written = await _complete_checked(
        gateway, messages, StoryReview, lambda r: check_review(r, said)
    )
    # After two misses, keep the last review's notes without the edits that are not the user's.
    review = written.output or written.last
    if review is None:
        return written
    notes: list[StoryReviewNote] = []
    for n in review.notes:
        edit = n.edit
        if edit is not None:
            if unbacked(edit.after, edit.quotes, said):
                edit = None
            else:
                edit = edit.model_copy(update={"before": story.part(n.part) or None})
        notes.append(n.model_copy(update={"edit": edit}))
    written.output = review.model_copy(update={"notes": notes})
    return written
