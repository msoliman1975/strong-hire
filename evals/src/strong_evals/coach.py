"""Coach evals (CO-9): simulated candidates talk to the real coach engine, then code checks the
result. The judge (`strong_evals.coach_judge`) checks what code cannot.

The session runs `strong_api.coach.engine.run_turn`, the code the coach API runs, with an
in-memory stand-in for the database. Nothing is written anywhere.

Candidates (`fixtures/coach/candidates.yaml`): vague, overclaim, off_topic and strong. On the
fake profile each one reads its script; on other profiles the candidate role plays it from its
facts with `prompts/evals/coach_candidate*`.

Code checks:
- invented facts (CO-9): every kept part update quotes the candidate word for word, and every
  number in the final story is one the candidate said.
- one question per coach reply (CO-4).
- word overlap of each story part with the candidate's turns, for information: a low overlap
  is worth a look, not a failure, because the coach may reword.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.coach import engine
from strong_api.coach.schemas import AskFor
from strong_core.db.models import CoachSession, CoachTurn
from strong_core.db.models import Story as StoryRow
from strong_core.gateway import Message, ModelGateway, Role
from strong_core.gateway.usage import set_usage_sink
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    AnswerConduct,
    CoachSessionStatus,
    CoachSpeaker,
    CoachStyle,
    Contract,
    SessionChannel,
    StoryPart,
    StoryPartUpdate,
    StorySource,
    StoryStatus,
    StoryVersions,
)
from strong_evals import EVALS_DIR

CANDIDATES_FILE = EVALS_DIR / "fixtures" / "coach" / "candidates.yaml"
PROMPT_ROLE = "evals"
STORY_TITLE = "Coach eval story"
MIN_OVERLAP = 0.6  # below this share of content words, a part is listed for review

_WORD = re.compile(r"[a-z][a-z'-]+")
_STOP_WORDS = (
    "about after again also because been before being both could does doing down during each "
    "from have having here into just more most much only other over same should some such "
    "than that their them then there these they this those through very were what when where "
    "which while with would your yours team"
)
_STOP = frozenset(_STOP_WORDS.split())


class CandidateKind(StrEnum):
    VAGUE = "vague"
    OVERCLAIM = "overclaim"
    OFF_TOPIC = "off_topic"
    STRONG = "strong"


class CoachCandidateSpec(Contract):
    """One simulated coach candidate. Synthetic people only."""

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    kind: CandidateKind
    name: str
    role: str
    facts: list[str] = Field(min_length=1)
    script: list[str] = Field(min_length=1, description="Turns on the fake profile.")


def load_candidates(path: Path = CANDIDATES_FILE) -> dict[str, CoachCandidateSpec]:
    rows = yaml.safe_load(path.read_text(encoding="utf-8"))
    specs = [CoachCandidateSpec.model_validate(r) for r in rows]
    return {s.id: s for s in specs}


class CoachCandidate:
    """The candidate side: the script on the fake profile, else the candidate role."""

    def __init__(self, spec: CoachCandidateSpec, gateway: ModelGateway) -> None:
        self.spec = spec
        self.gateway = gateway
        self.scripted = gateway.is_fake
        guide = load_prompt(PROMPT_ROLE, f"coach_candidate_{spec.kind.value}")
        self.system = load_prompt(PROMPT_ROLE, "coach_candidate").message(
            "system",
            name=spec.name,
            job=spec.role,
            facts="\n".join(f"- {f}" for f in spec.facts),
            kind_guide=guide.render(),
        )

    @property
    def max_turns(self) -> int | None:
        return len(self.spec.script) if self.scripted else None

    async def reply(self, turns: Sequence[CoachTurn]) -> str:
        if self.scripted:
            said = sum(t.speaker == CoachSpeaker.CANDIDATE for t in turns)
            return self.spec.script[said]
        messages = [self.system] + [
            Message(role="user" if t.speaker == CoachSpeaker.COACH else "assistant", content=t.text)
            for t in turns
        ]
        done = await self.gateway.complete(Role.CANDIDATE, messages)
        return done.output.strip()


class _Rows:
    def __init__(self, items: list[str]) -> None:
        self.items = items

    def all(self) -> list[str]:
        return self.items


class MemoryDb:
    """What `engine.run_turn` needs from AsyncSession: add, flush and the candidate-words query.
    One session on one story, so the query is every candidate turn of this run."""

    def __init__(self, turns: list[CoachTurn]) -> None:
        self.turns = turns

    def add(self, _row: object) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def scalars(self, _query: object) -> _Rows:
        return _Rows([t.text for t in self.turns if t.speaker == CoachSpeaker.CANDIDATE])


@dataclass
class CoachStep:
    """One candidate turn and the coach's reply."""

    candidate: str
    coach: str
    asked_for: AskFor  # what the story lacked before the reply; the model was told to ask it
    conduct: AnswerConduct
    kept: list[dict[str, Any]] = field(default_factory=list)  # part updates the engine kept
    dropped: list[str] = field(default_factory=list)  # and why it dropped the others


@dataclass
class CoachRun:
    candidate: CoachCandidateSpec
    style: CoachStyle
    opener: str
    steps: list[CoachStep]
    story: dict[str, str | None]  # part -> text at the end
    ended: bool  # the coach ended the session (IV-12 strikes)

    @property
    def candidate_text(self) -> str:
        return "\n".join(s.candidate for s in self.steps)


async def run_coach_session(
    spec: CoachCandidateSpec,
    style: CoachStyle,
    gateway: ModelGateway,
    *,
    max_turns: int = 6,
) -> CoachRun:
    """A text coach session on a new story, through the real engine."""
    org, user = uuid.uuid4(), uuid.uuid4()
    story = StoryRow(
        id=uuid.uuid4(),
        org_id=org,
        user_id=user,
        title=STORY_TITLE,
        skills=[],
        notes_json=[],
        status=StoryStatus.DRAFT,
        source=StorySource.COACH,
    )
    session = CoachSession(
        id=uuid.uuid4(),
        org_id=org,
        user_id=user,
        story_id=story.id,
        style=style,
        channel=SessionChannel.TEXT,
        status=CoachSessionStatus.ACTIVE,
        minutes=0,
        started_at=datetime.now(UTC),
    )
    turns: list[CoachTurn] = []
    db = cast(AsyncSession, MemoryDb(turns))
    opener = engine.opener(story, is_new=True, target_skill=None)
    engine.add_turn(db, session, turns, CoachSpeaker.COACH, opener)
    candidate = CoachCandidate(spec, gateway)
    limit = min(max_turns, candidate.max_turns or max_turns)
    steps: list[CoachStep] = []
    refs: set[str] = set()
    ended = False
    # The engine opens a usage context; its default sink writes to the database. The metered
    # gateway already counts the cost, so no sink here.
    previous = set_usage_sink(None)
    try:
        for _ in range(limit):
            text = await candidate.reply(turns)
            asked_for = engine.asks(story)[0]
            result = await engine.run_turn(db, gateway, session, story, turns, text, refs)
            steps.append(
                CoachStep(
                    candidate=text,
                    coach=result.reply.message,
                    asked_for=asked_for,
                    conduct=result.conduct,
                    kept=[p.model_dump(mode="json") for p in result.reply.parts],
                    dropped=result.dropped,
                )
            )
            if result.ended:
                ended = True
                break
    finally:
        set_usage_sink(previous)
    parts = {p.value: engine.part_text(story, p) for p in StoryPart}
    return CoachRun(spec, style, opener, steps, parts, ended)


# --- code checks -----------------------------------------------------------------------------


def _content_words(text: str) -> set[str]:
    words = _WORD.findall(engine._normal(text))
    return {_stem(w) for w in words if len(w) >= 4 and w not in _STOP}


def _stem(word: str) -> str:
    for end in ("ing", "ed", "es", "s"):
        if word.endswith(end) and len(word) - len(end) >= 4:
            return word[: -len(end)]
    return word


def unbacked_updates(run: CoachRun) -> list[str]:
    """CO-9: kept part updates whose quotes are not the candidate's words, or whose numbers
    are not in the quotes. The engine drops these, so this list must stay empty."""
    said = "\n".join(engine._normal(s.candidate) for s in run.steps)
    out: list[str] = []
    for i, step in enumerate(run.steps, start=1):
        for raw in step.kept:
            update = StoryPartUpdate.model_validate(raw)
            why = engine.backed(update, said)
            if why is not None:
                out.append(f"turn {i}, {update.part.value}: {why}")
    return out


def untraced_numbers(run: CoachRun) -> list[str]:
    """CO-9: numbers in the final story that the candidate never said."""
    said = set(engine._NUMBER.findall(engine._normal(run.candidate_text)))
    out: list[str] = []
    for part, text in run.story.items():
        for number in engine._NUMBER.findall(text or ""):
            if number not in said:
                out.append(f"{part}: {number}")
    return out


def part_overlap(run: CoachRun) -> dict[str, float]:
    """Share of each filled part's content words that the candidate used (information)."""
    said = _content_words(run.candidate_text)
    out: dict[str, float] = {}
    for part, text in run.story.items():
        words = _content_words(text or "")
        if words:
            out[part] = len(words & said) / len(words)
    return out


def low_overlap_parts(run: CoachRun) -> list[str]:
    return [f"{p}: {v:.0%}" for p, v in part_overlap(run).items() if v < MIN_OVERLAP]


def coach_replies(run: CoachRun) -> list[str]:
    """The coach's own replies; the fixed IV-12 warning lines are left out."""
    return [s.coach for s in run.steps if s.conduct == AnswerConduct.OK]


def one_question_count(run: CoachRun) -> tuple[int, int]:
    """CO-4: (replies with at most one question, replies)."""
    replies = coach_replies(run)
    return sum(r.count("?") <= 1 for r in replies), len(replies)


def versions_unbacked(versions: StoryVersions, said: str) -> list[str]:
    """CO-8, CO-9: versions whose quotes are not the candidate's words, or whose text has a
    number that is not in its quotes. `said` is the candidate's words, normalized."""
    out: list[str] = []
    for name, version in (("sixty_second", versions.sixty_second), ("full", versions.full)):
        update = StoryPartUpdate(part=StoryPart.CONTEXT, text=version.text, quotes=version.quotes)
        why = engine.backed(update, said)
        if why is not None:
            out.append(f"{name}: {why}")
    return out


def render_transcript(run: CoachRun, *, asked_for: bool = False) -> str:
    lines = [f"0 C: {run.opener}"]
    for i, step in enumerate(run.steps, start=1):
        lines.append(f"{i} K: {step.candidate}")
        hint = f" [asked for: {step.asked_for.value}]" if asked_for else ""
        lines.append(f"{i} C:{hint} {step.coach}")
    return "\n".join(lines)


def render_story(run: CoachRun) -> str:
    return "\n".join(f"{part}: {text or '(empty)'}" for part, text in run.story.items())
