"""SR-1 (spike): the story radar reads the caption stream off the voice loop's turn path."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from strong_core.db.models import Base, CoachSession, Story
from strong_core.gateway import Message
from strong_core.schemas import (
    CoachSessionStatus,
    CoachStyle,
    SessionChannel,
    StoryPart,
    StorySource,
    StoryStatus,
)
from strong_voice.latency import main as latency_main
from strong_voice.radar import (
    PROBE_STORIES,
    RadarReading,
    RadarSettings,
    StoryRadar,
    attach_radar,
    load_radar_stories,
    radar_message,
    radar_messages,
)

Maker = async_sessionmaker[AsyncSession]
BILLING = PROBE_STORIES[0].id


class FakeExtractor:
    """Returns readings in order; records the answers it was asked about."""

    def __init__(self, *readings: RadarReading, delay_s: float = 0.0, fail: bool = False) -> None:
        self.readings = list(readings)
        self.answers: list[str] = []
        self.delay_s = delay_s
        self.fail = fail

    async def __call__(self, messages: list[Message]) -> RadarReading:
        self.answers.append(messages[-1].content)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.fail:
            raise RuntimeError("model down")
        return self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]


class Sent:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def __call__(self, payload: bytes) -> None:
        self.messages.append(json.loads(payload))


def reading(story_id: str | None, *covered: StoryPart, current: StoryPart | None = None) -> Any:
    return RadarReading(story_id=story_id, covered=list(covered), current=current)


async def until(check: Callable[[], bool], timeout_s: float = 2.0) -> None:
    for _ in range(int(timeout_s / 0.005)):
        if check():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("timed out")


async def test_sr1_on_caption_never_waits_for_the_model() -> None:
    """SR-1: the caption handler returns at once even while a slow read is in flight."""
    extractor = FakeExtractor(reading(BILLING, StoryPart.CONTEXT), delay_s=0.5)
    radar = StoryRadar(PROBE_STORIES, extractor, Sent(), interval_s=0.0)
    radar.start()
    radar.on_caption("I led the rebuild of our billing service.")
    await until(lambda: radar.calls == 1)
    loop = asyncio.get_running_loop()
    started = loop.time()
    for _ in range(50):
        radar.on_caption("More words.")
    assert loop.time() - started < 0.05
    await radar.close()


async def test_sr1_reads_at_most_once_per_interval() -> None:
    """SR-1: many captions inside the interval make one more call, with all the words."""
    extractor = FakeExtractor(reading(BILLING, StoryPart.CONTEXT))
    sent = Sent()
    radar = StoryRadar(PROBE_STORIES, extractor, sent, interval_s=0.3)
    radar.start()
    radar.on_caption("I led the rebuild of our billing service.")
    await until(lambda: radar.calls == 1)
    for word in ("I wrote the design.", "I split the work.", "Failed payments fell."):
        radar.on_caption(word)
    await asyncio.sleep(0.1)
    assert radar.calls == 1  # still inside the interval
    await until(lambda: radar.calls == 2)
    await asyncio.sleep(0.4)
    assert radar.calls == 2  # no new words, no new call
    assert "Failed payments fell." in extractor.answers[-1]
    assert "billing service" in extractor.answers[-1]
    await radar.close()


async def test_sr1_publishes_the_story_and_the_covered_parts() -> None:
    """SR-1: the browser gets the story, the parts covered so far, and the current part."""
    extractor = FakeExtractor(
        reading(BILLING, StoryPart.CONTEXT, current=StoryPart.CONTEXT),
        reading(BILLING, StoryPart.ACTION, current=StoryPart.ACTION),
    )
    sent = Sent()
    radar = StoryRadar(PROBE_STORIES, extractor, sent, interval_s=0.0)
    radar.start()
    radar.on_caption("Our billing service failed a lot of payments.")
    await until(lambda: len(sent.messages) == 1)
    radar.on_caption("So I wrote the design and split the work.")
    await until(lambda: len(sent.messages) == 2)
    assert sent.messages[0] == {
        "type": "story_radar",
        "story_id": BILLING,
        "covered": ["context"],
        "current": "context",
    }
    # Parts once covered stay covered, in story order.
    assert sent.messages[1]["covered"] == ["context", "action"]
    assert sent.messages[1]["current"] == "action"
    await radar.close()


async def test_sr1_unknown_story_reads_as_none_and_repeats_are_not_sent() -> None:
    """SR-1: a story id the candidate does not have is no story; the same reading is sent once."""
    extractor = FakeExtractor(reading("made-up", StoryPart.RESULT))
    sent = Sent()
    radar = StoryRadar(PROBE_STORIES, extractor, sent, interval_s=0.0)
    radar.start()
    radar.on_caption("Something unrelated.")
    await until(lambda: len(sent.messages) == 1)
    radar.on_caption("Still unrelated.")
    await until(lambda: radar.calls == 2)
    await asyncio.sleep(0.05)
    assert sent.messages == [
        {"type": "story_radar", "story_id": None, "covered": [], "current": None}
    ]
    await radar.close()


async def test_sr1_failed_or_slow_reads_are_dropped() -> None:
    """SR-1: a failed or timed-out read sends nothing and the radar keeps going."""
    sent = Sent()
    failing = StoryRadar(PROBE_STORIES, FakeExtractor(reading(None), fail=True), sent)
    failing.start()
    failing.on_caption("Hello.")
    await until(lambda: failing.calls == 1)
    await failing.close()
    slow = StoryRadar(
        PROBE_STORIES, FakeExtractor(reading(BILLING), delay_s=1.0), sent, timeout_s=0.05
    )
    await slow.read_once()
    assert sent.messages == [] and slow.reading is None


async def test_sr1_interim_and_empty_captions_and_no_stories_make_no_call() -> None:
    """SR-1: only final, non-empty captions count, and a candidate with no stories costs nothing."""
    extractor = FakeExtractor(reading(BILLING))
    radar = StoryRadar(PROBE_STORIES, extractor, Sent(), interval_s=0.0)
    radar.start()
    radar.on_caption("I led the", is_final=False)
    radar.on_caption("   ")
    empty = StoryRadar([], extractor, Sent(), interval_s=0.0)
    empty.start()
    empty.on_caption("I led the rebuild.")
    await asyncio.sleep(0.05)
    assert radar.calls == 0 and empty.calls == 0
    await radar.close()
    await empty.close()


class FakeAgentSession:
    def __init__(self) -> None:
        self.handlers: dict[str, Callable[[Any], None]] = {}

    def on(self, name: str, fn: Callable[[Any], None]) -> None:
        self.handlers[name] = fn


async def test_sr1_attach_reads_the_final_captions() -> None:
    """SR-1: the radar listens to `user_input_transcribed` and keeps only final transcripts."""
    session = FakeAgentSession()
    extractor = FakeExtractor(reading(BILLING, StoryPart.CONTEXT))
    sent = Sent()
    radar = attach_radar(session, PROBE_STORIES, extractor, sent, RadarSettings(interval_s=0))
    event = type("Ev", (), {"transcript": "Billing failed.", "is_final": True})()
    session.handlers["user_input_transcribed"](event)
    await until(lambda: len(sent.messages) == 1)
    await radar.close()


def test_sr1_settings_are_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """SR-1: the radar is off in coach rooms and latency rooms unless switched on."""
    monkeypatch.delenv("STORY_RADAR_ENABLED", raising=False)
    monkeypatch.delenv("STORY_RADAR_PROBE", raising=False)
    settings = RadarSettings(_env_file=None)  # type: ignore[call-arg]
    assert not settings.enabled and not settings.probe and settings.interval_s >= 2


def test_sr1_prompt_holds_the_stories_and_the_answer() -> None:
    """SR-1: the extractor prompt carries every story, its parts and the answer as data."""
    system, user = radar_messages(PROBE_STORIES, "I led the rebuild.")
    assert system.prompt_ref == "extractor/story_radar.v1"
    assert user.prompt_ref == "extractor/story_radar_input.v1"
    for story in PROBE_STORIES:
        assert story.id in user.content and story.title in user.content
    assert "<untrusted_input>\nI led the rebuild.\n</untrusted_input>" in user.content
    assert json.loads(radar_message(reading(None)))["type"] == "story_radar"


@pytest.fixture
async def maker() -> AsyncIterator[Maker]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        tables = [Base.metadata.tables["stories"], Base.metadata.tables["coach_sessions"]]
        await conn.run_sync(Base.metadata.create_all, tables=tables)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_sr1_loads_the_candidates_own_stories(maker: Maker) -> None:
    """SR-1: the radar matches against the session owner's stories only, newest first."""
    org, user = uuid.uuid4(), uuid.uuid4()
    session = CoachSession(
        id=uuid.uuid4(),
        org_id=org,
        user_id=user,
        style=CoachStyle.GENTLE,
        channel=SessionChannel.VOICE,
        status=CoachSessionStatus.ACTIVE,
        minutes=0,
    )
    at = datetime(2026, 10, 1, tzinfo=UTC)

    def story(owner: uuid.UUID, title: str, days: int, **parts: str) -> Story:
        return Story(
            id=uuid.uuid4(),
            org_id=org,
            user_id=owner,
            title=title,
            skills=["ownership"],
            status=StoryStatus.DRAFT,
            source=StorySource.COACH,
            created_at=at,
            updated_at=at + timedelta(days=days),
            **parts,
        )

    async with maker() as db:
        db.add(session)
        db.add(story(user, "Old", 1, context="Billing"))
        db.add(story(user, "New", 2, context="Outage", result="Back in an hour"))
        db.add(story(uuid.uuid4(), "Someone else's", 3))
        await db.commit()

    stories = await load_radar_stories(maker, session.id)
    assert [s.title for s in stories] == ["New", "Old"]
    assert stories[0].parts == {StoryPart.CONTEXT: "Outage", StoryPart.RESULT: "Back in an hour"}
    assert await load_radar_stories(maker, uuid.uuid4()) == []


def test_sr1_latency_report_by_file(tmp_path: Any, capsys: pytest.CaptureFixture[str]) -> None:
    """SR-1: the latency report puts the runs with and without the radar side by side."""
    header = "timestamp,session,profile,turn,total_ms,turn_detection_ms,stt_ms,llm_ttft_ms,"
    header += "tts_ttfb_ms,other_ms,interrupted\n"
    for name, total in (("hosted", 700), ("hosted-radar", 720)):
        row = f"1,s,hosted,1,{total},100,100,200,100,{total - 500},False\n"
        (tmp_path / f"{name}.csv").write_text(header + row, encoding="utf-8")
    assert latency_main(["report", "--by-file", *(str(p) for p in sorted(tmp_path.iterdir()))]) == 0
    out = capsys.readouterr().out
    assert "hosted p95" in out and "hosted-radar p95" in out
