"""OB-3: per-turn latency of real interviews is saved to voice_turn_timings, off the turn loop."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from strong_core.db.models import Base, VoiceTurnTiming
from strong_voice.latency import LatencyRecorder
from strong_voice.session_store import SqlTimingStore

USER = {"end_of_turn_delay": 0.45, "transcription_delay": 0.20}
REPLY = {"e2e_latency": 0.90, "llm_node_ttft": 0.25, "tts_node_ttfb": 0.12}
ORG, SID = uuid.uuid4(), uuid.uuid4()

Maker = async_sessionmaker[AsyncSession]


@pytest.fixture
async def maker() -> AsyncIterator[Maker]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        tables = [Base.metadata.tables["voice_turn_timings"]]
        await conn.run_sync(Base.metadata.create_all, tables=tables)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_ob3_turn_timings_are_saved_in_batches_and_at_the_end(maker: Maker) -> None:
    store = SqlTimingStore(maker, ORG, SID, flush_every=2)
    recorder = LatencyRecorder(None, session=f"session-{SID}", profile="local", on_turn=store.add)
    for _ in range(3):
        recorder.on_message("user", USER)
        recorder.on_message("assistant", {**REPLY, "llm_node_ttft": None})
    await asyncio.sleep(0)  # the batch of two is written by a background task
    assert len(store.pending) == 1  # add() did not wait for the database
    await store.close()
    async with maker() as db:
        rows = list(await db.scalars(select(VoiceTurnTiming).order_by(VoiceTurnTiming.turn_index)))
    assert [r.turn_index for r in rows] == [1, 2, 3]
    first = rows[0]
    assert first.org_id == ORG and first.session_id == SID
    assert (first.e2e_ms, first.stt_ms, first.turn_detection_ms, first.tts_ttfb_ms) == (
        900,
        200,
        250,
        120,
    )
    assert first.llm_ttft_ms is None  # not reported: NULL, not 0


async def test_ob3_a_database_failure_never_reaches_the_turn_loop() -> None:
    def broken() -> object:
        raise RuntimeError("database down")

    store = SqlTimingStore(broken, ORG, SID, flush_every=1)  # type: ignore[arg-type]
    recorder = LatencyRecorder(None, session="s", profile="local", on_turn=store.add)
    recorder.on_message("user", USER)
    recorder.on_message("assistant", REPLY)  # schedules a write that fails in the background
    await store.close()
    assert len(recorder.turns) == 1


def test_ob3_a_failing_callback_is_logged_not_raised() -> None:
    def boom(_: object) -> None:
        raise ValueError("nope")

    recorder = LatencyRecorder(None, session="s", profile="local", on_turn=boom)
    recorder.on_message("user", USER)
    recorder.on_message("assistant", REPLY)
    assert len(recorder.turns) == 1
