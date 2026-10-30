"""ST-13: Ask Strova on Career Stories. The coach role answers a question from the user's own
stories and target roles (prompt coach/ask, contract StoryAnswer).

Code then checks the reply, as CO-9 asks: story ids are only the user's own, every quote is the
user's words from a story, and every number in the answer is in those words. A reply that fails
is asked for once more (prompt coach/suggest_fix); a second miss gives the plain fallback, so
Strova never states a fact the user did not write.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from strong_api.coach.engine import PARTS, _normal, part_text, quote_found
from strong_core.db.models import JobTarget
from strong_core.db.models import Story as StoryRow
from strong_core.gateway import Message, ModelGateway, Role
from strong_core.prompts import load_prompt
from strong_core.schemas import JobPosting, StoryAnswer

ROLE = Role.COACH
FALLBACK = "I can't answer that from your stories yet. Add a story that shows it, and ask me again."
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
MAX_STORIES = 30


@dataclass
class Asked:
    answer: StoryAnswer
    prompt_refs: tuple[str, ...]
    checked: bool
    """False when the fallback was given after two replies failed the check."""


def _clip(text: str, limit: int = 600) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit]


def render_stories(stories: Sequence[StoryRow]) -> str:
    out: list[str] = []
    for s in stories[:MAX_STORIES]:
        lines = [f"Story {s.id}: {_clip(s.title, 200)}"]
        lines += [f"  {p.value}: {_clip(t)}" for p in PARTS if (t := part_text(s, p))]
        out.append("\n".join(lines))
    return "\n\n".join(out) or "(no stories yet)"


def render_roles(targets: Sequence[JobTarget]) -> str:
    names: list[str] = []
    for t in targets:
        if t.parsed_json:
            posting = JobPosting.model_validate(t.parsed_json)
            names.append(f"{posting.title} at {posting.company_name}")
        elif t.name:
            names.append(t.name)
    return "\n".join(f"- {n}" for n in names) or "(no target roles yet)"


def problems(answer: StoryAnswer, said: str, ids: set[str]) -> list[str]:
    out = [f"not one of the user's stories: {i}" for i in answer.story_ids if str(i) not in ids]
    out += [f"quote not found: {q[:80]!r}" for q in answer.quotes if not quote_found(q, said)]
    quoted = " ".join(_normal(q) for q in answer.quotes)
    out += [
        f"number not in the quotes: {n}" for n in _NUMBER.findall(answer.answer) if n not in quoted
    ]
    return out


async def ask_strova(
    gateway: ModelGateway,
    question: str,
    stories: Sequence[StoryRow],
    targets: Sequence[JobTarget],
) -> Asked:
    said = "\n".join(_normal(t) for s in stories for p in PARTS if (t := part_text(s, p)))
    ids = {str(s.id) for s in stories}
    messages: list[Message] = [
        load_prompt(ROLE, "ask").message("system"),
        load_prompt(ROLE, "ask_input").message(
            "user",
            question=_clip(question, 500),
            roles=render_roles(targets),
            stories=render_stories(stories),
        ),
    ]
    refs: list[str] = []
    for _attempt in (1, 2):
        done = await gateway.complete(ROLE, messages, output_type=StoryAnswer)
        refs += done.prompt_refs
        found = problems(done.output, said, ids)
        if not found:
            return Asked(done.output, tuple(dict.fromkeys(refs)), True)
        messages = [
            *messages,
            Message(role="assistant", content=done.output.model_dump_json()),
            load_prompt(ROLE, "suggest_fix").message(
                "user", problems="\n".join(f"- {p}" for p in found)
            ),
        ]
    return Asked(StoryAnswer(answer=FALLBACK), tuple(dict.fromkeys(refs)), False)
