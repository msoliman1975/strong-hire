"""Admin traces from the voice interview (R2): rows in interviewer_traces, written in the
background, with the move, the reason and the fixed lines."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from strong_core.config import ModelProfile, Settings
from strong_core.db.models import Base, InterviewerTrace, InterviewSession, JobTarget, Org, User
from strong_core.gateway import build_gateway
from strong_core.schemas import AuthProvider, Difficulty, InterviewType, Mode, Phase
from strong_interview import Interviewer, InterviewRunner, SessionController
from strong_interview.testing import FakeClock, make_brief
from strong_interview.trace import TraceRecord
from strong_interview.trace_store import SqlTraceSink
from strong_voice.interview import TAKE_YOUR_TIME, WELCOME_BACK, VoiceInterview


class NullStore:
    async def save_turn(self, session_id: uuid.UUID, turn: Any) -> None:
        return None

    async def save_usage(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def save_provenance(self, session_id: uuid.UUID, prompt_version: str | None) -> None:
        return None


class NullFinisher:
    async def finish(self, session_id: uuid.UUID, *, interrupted: bool) -> None:
        return None


@compiles(JSONB, "sqlite")
def _jsonb_on_sqlite(type_: Any, compiler: Any, **kw: Any) -> str:
    return "JSON"


Maker = async_sessionmaker[AsyncSession]


@pytest.fixture
async def maker() -> AsyncIterator[Maker]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _session(maker: Maker) -> tuple[uuid.UUID, uuid.UUID]:
    async with maker() as db:
        org = Org(name="ana")
        db.add(org)
        await db.flush()
        user = User(org_id=org.id, email="ana@example.com", auth_provider=AuthProvider.DEV)
        db.add(user)
        await db.flush()
        job = JobTarget(org_id=org.id, user_id=user.id, raw_text="Engineer")
        db.add(job)
        await db.flush()
        row = InterviewSession(
            org_id=org.id,
            job_target_id=job.id,
            type=InterviewType.BEHAVIORAL,
            difficulty=Difficulty.FRIENDLY,
            mode=Mode.REALISTIC,
            duration_min=30,
        )
        db.add(row)
        await db.commit()
        return org.id, row.id


async def test_r2_voice_session_writes_trace_rows(maker: Maker) -> None:
    org_id, sid = await _session(maker)
    clock, wall = FakeClock(), [0.0]
    brief = make_brief(difficulty=Difficulty.FRIENDLY)
    gateway = build_gateway(Settings(model_profile=ModelProfile.FAKE))
    sink = SqlTraceSink(maker, org_id, sid)
    runner = InterviewRunner(
        SessionController(brief, clock), Interviewer(gateway, brief), trace=sink
    )
    voice = VoiceInterview(sid, runner, NullStore(), NullFinisher(), now=lambda: wall[0])

    await voice.opening()
    await voice.on_candidate("Happy to be here.")
    await voice.on_candidate("Sounds good.")  # agenda + first question
    clock.advance(ms=30_000)
    await voice.on_thinking("Give me a moment.")
    await voice.on_candidate("We built a billing service and I led it.", 5.0)  # decide + probe
    voice.on_disconnect()
    assert voice.on_reconnect()[0] == WELCOME_BACK
    await sink.flush()

    async with maker() as db:
        rows = list(
            await db.scalars(
                select(InterviewerTrace)
                .where(InterviewerTrace.session_id == sid)
                .order_by(InterviewerTrace.seq)
            )
        )
    moves = [r.move for r in rows]
    assert moves == [
        "greet",
        "small_talk",
        "agenda",
        "ask",
        "take_your_time",
        "decide",
        "probe",
        "welcome_back",
    ]
    by_move = {r.move: r for r in rows}
    assert by_move["take_your_time"].spoken_text == TAKE_YOUR_TIME
    assert by_move["take_your_time"].call == "line"
    decide = by_move["decide"]
    assert decide.reason_json is not None
    assert decide.reason_json["decision"]["action"] == "probe"
    assert decide.messages_json and decide.raw_reply
    probe = by_move["probe"]
    assert probe.reason_json is not None and probe.reason_json["why"] == ["model_chose_probe"]
    assert probe.phase == Phase.CORE and probe.question_ref == "q1"
    assert probe.spoken_text and probe.model and probe.org_id == org_id
    assert all(r.elapsed_ms >= 0 and r.phase_deadline_ms for r in rows)


async def test_r2_voice_trace_writes_do_not_wait_for_the_database(maker: Maker) -> None:
    """write() returns before the insert runs; a failing insert is logged, not raised."""
    org_id, sid = await _session(maker)
    gate = asyncio.Event()

    class SlowMaker:
        def __call__(self) -> Any:
            return self

        async def __aenter__(self) -> Any:
            await gate.wait()
            raise RuntimeError("database down")

        async def __aexit__(self, *args: Any) -> None:
            return None

    sink = SqlTraceSink(SlowMaker(), org_id, sid)  # type: ignore[arg-type]
    record = TraceRecord(
        seq=1,
        turn_index=0,
        call="line",
        move="check_in",
        reason={},
        phase=Phase.CORE,
        elapsed_ms=0,
        phase_deadline_ms=None,
    )
    sink.write(record)  # returns at once, while the database "hangs"
    gate.set()
    await sink.flush()  # the error is swallowed
