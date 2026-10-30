"""Suggestion evals (SG-7): Strova's suggestions hold only the user's own words.

Each case in `fixtures/suggestions/cases.yaml` runs the product's writer
(`strong_worker.suggestions.generate`) for one kind: tune a story, new story, improve a resume
line or review. On the fake profile the model reply is the case's `reply`, so the suite checks
the check: a reply from the user's words is kept and a reply that adds a fact is rejected
(`expect`). Off the fake profile the real coach writes the reply, and every kept text is checked
again against the user's words.

Metric `suggestions_invented_facts` counts kept texts that are not the user's words, plus fake
cases whose result is not the expected one. It must be 0.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field

from strong_core.gateway import ModelGateway
from strong_core.gateway.registry import fake_models_config
from strong_core.schemas import Contract, Story, StoryPart
from strong_evals import EVALS_DIR
from strong_worker.scoring.testing import ScriptedBackend
from strong_worker.suggestions import facts, generate

CASES_FILE = EVALS_DIR / "fixtures" / "suggestions" / "cases.yaml"
Kind = Literal["tune_story", "new_story", "improve_resume_line", "review"]


class SuggestionCase(Contract):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    kind: Kind
    story: dict[str, str] = Field(default_factory=dict)
    answer: str = ""
    fix: str = ""
    question: str = ""
    line: str = ""
    said: list[str] = Field(default_factory=list)
    reply: dict[str, Any]
    expect: Literal["kept", "rejected"]


def load_cases(path: Path = CASES_FILE) -> dict[str, SuggestionCase]:
    items = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = [SuggestionCase.model_validate(i) for i in items]
    return {c.id: c for c in cases}


@dataclass
class SuggestionResult:
    case: SuggestionCase
    outcome: Literal["kept", "rejected"] | None = None
    texts: list[str] = field(default_factory=list)
    unbacked: list[str] = field(default_factory=list)
    """Kept texts that are not the user's words, checked again here."""
    calls: int = 0
    error: str | None = None

    @property
    def as_expected(self) -> bool:
        return self.outcome == self.case.expect


def _story(case: SuggestionCase) -> Story:
    now = datetime.now(UTC)
    return Story.model_validate(
        {
            "id": str(uuid.uuid4()),
            "title": case.story.get("title", "Story"),
            **{p.value: case.story.get(p.value) for p in StoryPart},
            "source": "manual",
            "created_at": now,
            "updated_at": now,
        }
    )


def _user_words(case: SuggestionCase, story: Story) -> str:
    if case.kind in ("tune_story", "new_story"):
        return facts.said_text([case.answer])
    words = generate.story_words(story)
    extra = [case.line] if case.kind == "improve_resume_line" else case.said
    return facts.said_text([*words, *extra])


async def run_case(case: SuggestionCase, base: ModelGateway) -> SuggestionResult:
    """One case through the writer; on the fake profile the reply is the case's."""
    result = SuggestionResult(case)
    gateway = base
    if base.profile == "fake":
        gateway = ModelGateway(fake_models_config(), fake=ScriptedBackend([case.reply]))
    story = _story(case)
    quotes: list[str] = []
    try:
        if case.kind == "tune_story":
            tune = await generate.tune_story(gateway, story, case.answer, case.fix)
            result.calls = tune.calls
            if tune.output is not None:
                result.texts, quotes = [tune.output.after], tune.output.quotes
        elif case.kind == "new_story":
            new = await generate.new_story(gateway, case.question, case.answer, [])
            result.calls = new.calls
            if new.output is not None:
                parts = [getattr(new.output, p.value) for p in StoryPart]
                result.texts, quotes = [t for t in parts if t], new.output.quotes
        elif case.kind == "improve_resume_line":
            line = await generate.improve_resume_line(
                gateway, story, "roles[0].achievements[0]", case.line
            )
            result.calls = line.calls
            if line.output is not None:
                result.texts, quotes = [line.output.after], line.output.quotes
        else:
            review = await generate.review_story(gateway, story, case.said)
            result.calls = review.calls
            asked = sum(1 for n in review.last.notes if n.edit) if review.last else 0
            edits = [n.edit for n in review.output.notes if n.edit] if review.output else []
            if review.output is not None and len(edits) == asked:
                result.texts = [e.after for e in edits]
                quotes = [q for e in edits for q in e.quotes]
            else:
                result.outcome = "rejected"
    except Exception as exc:  # one case never stops the suite
        result.error = f"{type(exc).__name__}: {exc}"
        return result
    if result.outcome is None:
        result.outcome = "kept" if result.texts else "rejected"
    said = _user_words(case, story)
    for text in result.texts:
        result.unbacked += facts.unbacked(text, quotes, said)
    return result


def invented_facts(results: list[SuggestionResult], fake: bool) -> int:
    """SG-7: kept texts not in the user's words, and on the fake profile unexpected outcomes."""
    count = sum(bool(r.unbacked) for r in results if r.outcome == "kept")
    if fake:
        count += sum(not r.as_expected for r in results if r.error is None)
    return count
