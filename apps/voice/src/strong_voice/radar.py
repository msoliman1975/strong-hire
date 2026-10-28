"""Story radar (SR-1, spike): which story the candidate is telling and which parts they covered.

The radar runs on the caption stream, beside the voice loop and never in it. `on_caption` only
keeps the final transcript and wakes the radar's own task; nothing on the turn path awaits the
radar. The task asks the extractor role (prompt `extractor/story_radar`) at most once every
`interval_s`, and only when there are new words. A slow or failed call is dropped: the next
caption tries again.

To the browser (topic "session"), when the reading changes:
  {"type": "story_radar", "story_id": str | null, "covered": [parts], "current": part | null}

Switches (environment, off by default):
  STORY_RADAR_ENABLED=1   run the radar in voice coach rooms
  STORY_RADAR_PROBE=1     run it in latency spike rooms, against PROBE_STORIES, to measure what
                          it costs the voice loop (set LATENCY_LABEL to keep a separate CSV)

SR-1 ships only if p95 voice latency does not rise with the radar on. Until that is measured on
the hosted profile, the browser never shows it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import CoachSession, Story
from strong_core.gateway import Message, ModelGateway, Role
from strong_core.prompts import load_prompt
from strong_core.schemas import StoryPart

log = logging.getLogger(__name__)

RADAR_MESSAGE = "story_radar"
MAX_STORIES = 12
PART_NOTE_CHARS = 120


class RadarSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STORY_RADAR_", env_file=".env", extra="ignore")

    enabled: bool = False
    probe: bool = False
    interval_s: float = 4.0
    timeout_s: float = 8.0
    max_answer_chars: int = 2000


@lru_cache
def get_radar_settings() -> RadarSettings:
    return RadarSettings()


class RadarReading(BaseModel):
    """What the extractor reads from the answer so far."""

    model_config = ConfigDict(extra="forbid")

    story_id: str | None
    covered: list[StoryPart]
    current: StoryPart | None


@dataclass(frozen=True)
class RadarStory:
    id: str
    title: str
    parts: dict[StoryPart, str] = field(default_factory=dict)


# The latency caller's two answers (strong_voice.caller.ANSWERS) match the first two stories.
PROBE_STORIES = (
    RadarStory(
        "probe-billing",
        "Billing service rebuild",
        {
            StoryPart.CONTEXT: "Failed payments in the billing service",
            StoryPart.ACTION: "Wrote the design, split the work across three engineers",
            StoryPart.RESULT: "Failed payments down forty percent in two months",
        },
    ),
    RadarStory(
        "probe-rewrite",
        "Talking a teammate out of a rewrite",
        {
            StoryPart.CONTEXT: "A teammate wanted to rewrite the API",
            StoryPart.ACTION: "Measured the real problems for a week",
            StoryPart.RESULT: "Fixed two slow queries, skipped the rewrite",
        },
    ),
    RadarStory("probe-oncall", "On-call outage", {StoryPart.CONTEXT: "A night outage"}),
)


def render_stories(stories: Sequence[RadarStory]) -> str:
    lines = []
    for s in stories:
        lines.append(f"- id {s.id}: {s.title}")
        for part in StoryPart:
            note = s.parts.get(part)
            if note:
                lines.append(f"  {part.value}: {note[:PART_NOTE_CHARS]}")
    return "\n".join(lines)


def radar_messages(stories: Sequence[RadarStory], answer: str) -> list[Message]:
    return [
        load_prompt(Role.EXTRACTOR, "story_radar").message("system"),
        load_prompt(Role.EXTRACTOR, "story_radar_input").message(
            "user", stories=render_stories(stories), answer=answer
        ),
    ]


Complete = Callable[[list[Message]], Awaitable[RadarReading]]
Publish = Callable[[bytes], Awaitable[None]]


def gateway_complete(gateway: ModelGateway) -> Complete:
    async def complete(messages: list[Message]) -> RadarReading:
        done = await gateway.complete(Role.EXTRACTOR, messages, output_type=RadarReading)
        return done.output

    return complete


def radar_message(reading: RadarReading) -> bytes:
    return json.dumps({"type": RADAR_MESSAGE, **reading.model_dump(mode="json")}).encode()


class StoryRadar:
    """Reads the caption stream in its own task. Start it once; close it when the room ends."""

    def __init__(
        self,
        stories: Sequence[RadarStory],
        complete: Complete,
        publish: Publish,
        *,
        interval_s: float = 4.0,
        timeout_s: float = 8.0,
        max_answer_chars: int = 2000,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.stories = list(stories)
        self._ids = {s.id for s in self.stories}
        self._complete = complete
        self._publish = publish
        self.interval_s = interval_s
        self.timeout_s = timeout_s
        self.max_answer_chars = max_answer_chars
        self._now = now
        self._captions: list[str] = []
        self._new = asyncio.Event()
        self._last_call: float | None = None
        self._task: asyncio.Task[None] | None = None
        self.reading: RadarReading | None = None
        self.calls = 0

    def on_caption(self, text: str, is_final: bool = True) -> None:
        """Called from the caption event. Never blocks and never raises."""
        text = text.strip()
        if not is_final or not text or not self.stories:
            return
        self._captions.append(text)
        self._new.set()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="story-radar")

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            await self._new.wait()
            if self._last_call is not None:
                wait = self._last_call + self.interval_s - self._now()
                if wait > 0:
                    await asyncio.sleep(wait)
            self._new.clear()
            self._last_call = self._now()
            await self.read_once()

    async def read_once(self) -> None:
        answer = " ".join(self._captions)[-self.max_answer_chars :]
        self.calls += 1
        try:
            reading = await asyncio.wait_for(
                self._complete(radar_messages(self.stories, answer)), self.timeout_s
            )
        except Exception:
            log.info("story radar read failed; waiting for the next caption", exc_info=True)
            return
        reading = self._merge(reading)
        if reading == self.reading:
            return
        self.reading = reading
        try:
            await self._publish(radar_message(reading))
        except Exception:
            log.warning("could not send the story radar to the browser", exc_info=True)

    def _merge(self, reading: RadarReading) -> RadarReading:
        """Unknown story ids read as no story. Parts once covered stay covered for that story."""
        story_id = reading.story_id if reading.story_id in self._ids else None
        if story_id is None:
            return RadarReading(story_id=None, covered=[], current=None)
        covered = set(reading.covered)
        if self.reading is not None and self.reading.story_id == story_id:
            covered |= set(self.reading.covered)
        ordered = [p for p in StoryPart if p in covered]
        return RadarReading(story_id=story_id, covered=ordered, current=reading.current)


def attach_radar(
    agent_session: Any,
    stories: Sequence[RadarStory],
    complete: Complete,
    publish: Publish,
    settings: RadarSettings | None = None,
) -> StoryRadar:
    """Start a radar on the session's final captions (`user_input_transcribed`)."""
    settings = settings or get_radar_settings()
    radar = StoryRadar(
        stories,
        complete,
        publish,
        interval_s=settings.interval_s,
        timeout_s=settings.timeout_s,
        max_answer_chars=settings.max_answer_chars,
    )

    def _on_caption(event: Any) -> None:
        radar.on_caption(event.transcript, event.is_final)

    agent_session.on("user_input_transcribed", _on_caption)
    radar.start()
    return radar


async def load_radar_stories(
    maker: async_sessionmaker[AsyncSession], coach_session_id: uuid.UUID
) -> list[RadarStory]:
    """The coach session owner's most recent stories, with a short note per filled part."""
    async with maker() as db:
        session = await db.get(CoachSession, coach_session_id)
        if session is None:
            return []
        rows = await db.scalars(
            select(Story)
            .where(Story.org_id == session.org_id, Story.user_id == session.user_id)
            .order_by(Story.updated_at.desc())
            .limit(MAX_STORIES)
        )
        return [
            RadarStory(
                str(row.id),
                row.title,
                {p: text for p in StoryPart if (text := getattr(row, p.value))},
            )
            for row in rows
        ]
