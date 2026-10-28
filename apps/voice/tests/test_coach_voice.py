"""CO-6: coach sessions run by voice on the interview's voice loop, with spoken takes."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from livekit import rtc
from livekit.agents import AgentSession
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from strong_core.config import Settings
from strong_core.db.models import Base, CoachSession, CoachTurn
from strong_core.gateway import ModelGateway, build_gateway
from strong_core.schemas import CoachSessionStatus, CoachSpeaker, CoachStyle, SessionChannel
from strong_voice import coach_agent
from strong_voice.coach import (
    SAY_AGAIN,
    TAKE_CANCELLED,
    TAKE_DONE,
    TAKE_EMPTY,
    TAKE_STARTED,
    CoachTurnError,
    VoiceCoach,
    VoiceTake,
)
from strong_voice.coach_agent import CoachAgent, take_message, turn_message
from strong_voice.coach_store import (
    ApiCoach,
    coach_session_id_from_room,
    load_coach_session,
)
from strong_voice.interview import RECONNECT_S, TAKE_YOUR_TIME, WELCOME_BACK
from strong_voice.plugins import GatewaySTT, GatewayTTS
from strong_voice.session_store import AgentApiSettings, session_id_from_room
from strong_voice.turns import CandidateTurns

SID = uuid.uuid4()
OPENER = "Tell me about a time you led a hard change."
WRITES = re.compile(r"open\([^)]*['\"]w|write_bytes|\.wav|wave\.open|AudioFrame\(")


@dataclass
class FakeApi:
    """The API's coach turn logic: records each turn and answers from a script."""

    replies: list[str] = field(default_factory=lambda: ["What was at stake?", "What did you do?"])
    turns: list[str] = field(default_factory=list)
    ends: int = 0
    fail_next: bool = False
    end_on: int | None = None  # the API ends the session on this turn (IV-12, third warning)

    async def turn(self, session_id: uuid.UUID, text: str) -> dict[str, Any]:
        assert session_id == SID
        if self.fail_next:
            self.fail_next = False
            raise CoachTurnError("timeout")
        self.turns.append(text)
        ended = self.end_on == len(self.turns)
        message = "We'll stop here." if ended else self.replies[len(self.turns) - 1]
        return {"reply": {"message": message, "parts": [], "missing": []}, "ended": ended}

    async def end(self, session_id: uuid.UUID) -> None:
        self.ends += 1


def make_coach(api: FakeApi | None = None) -> tuple[VoiceCoach, FakeApi, list[float]]:
    api = api or FakeApi()
    wall = [0.0]
    return VoiceCoach(SID, api, now=lambda: wall[0], opener=OPENER), api, wall


def make_turns(coach: VoiceCoach) -> tuple[CandidateTurns, list[str]]:
    said: list[str] = []

    async def speak(lines: list[str]) -> None:
        said.extend(lines)

    return CandidateTurns(coach, speak, thinking_wait_s=60.0, resume_wait_s=0.05), said


def test_co6_coach_room_names() -> None:
    sid = uuid.uuid4()
    assert coach_session_id_from_room(f"coach-{sid}") == sid
    assert coach_session_id_from_room("coach-nope") is None
    assert coach_session_id_from_room(f"session-{sid}") is None
    assert session_id_from_room(f"coach-{sid}") is None  # never taken for an interview


async def test_co6_opening_is_the_coach_line_the_api_wrote() -> None:
    coach, _, _ = make_coach()
    assert await coach.opening() == [OPENER]
    assert await VoiceCoach(SID, FakeApi(), now=lambda: 0.0).opening() == []


async def test_co6_each_turn_goes_to_the_api_coach_and_its_reply_is_spoken() -> None:
    coach, api, _ = make_coach()
    turns, said = make_turns(coach)
    await turns.on_turn("I moved our team to trunk-based development.", 6.0)
    assert api.turns == ["I moved our team to trunk-based development."]
    assert said == ["What was at stake?"]
    assert coach.last_result is not None and coach.last_result["reply"]["message"] == said[0]
    assert not coach.ended


async def test_co6_turn_taking_is_the_interviews() -> None:
    """Thinking requests get one line and no API call; minutes asked for start no prep timer."""
    coach, api, _ = make_coach()
    turns, said = make_turns(coach)
    await turns.on_turn("Let me think about that.")
    await turns.on_turn("Give me 3 minutes.")
    assert said == [TAKE_YOUR_TIME, TAKE_YOUR_TIME]
    assert api.turns == []
    assert not coach.preparing and await coach.check_in() == []
    turns.close()


async def test_co6_a_reply_is_never_taken_back() -> None:
    """The API saved the turn, so the reply is spoken even if the candidate went on talking."""
    coach, api, _ = make_coach()
    assert await coach.on_candidate("We had two outages a week.", superseded=lambda: True) == [
        "What was at stake?"
    ]
    assert api.turns == ["We had two outages a week."]


async def test_co6_a_failed_turn_asks_the_candidate_again() -> None:
    coach, _, _ = make_coach(FakeApi(fail_next=True))
    assert await coach.on_candidate("It cut deploy time in half.") == [SAY_AGAIN]
    assert not coach.ended
    assert await coach.on_candidate("It cut deploy time in half.") == ["What was at stake?"]


async def test_co6_session_ends_when_the_candidate_ends_it_once() -> None:
    coach, api, _ = make_coach()
    await coach.on_candidate("Hi.")
    await coach.finish()
    await coach.finish()
    assert coach.ended and api.ends == 1
    assert await coach.on_candidate("Hello?") == []


async def test_co6_the_api_can_end_the_session() -> None:
    coach, api, _ = make_coach(FakeApi(end_on=1))
    assert await coach.on_candidate("...") == ["We'll stop here."]
    assert coach.ended
    await coach.finish()
    assert api.ends == 1  # ending an ended session is harmless in the API


async def test_co6_voice_take_keeps_the_words_and_stays_quiet() -> None:
    coach, api, wall = make_coach()
    turns, said = make_turns(coach)
    assert coach.start_take() == [TAKE_STARTED]
    assert coach.start_take() == []  # already recording
    await turns.on_turn("Our deploys took forty minutes.", 4.0)
    await turns.on_turn("Let me think.", 1.0)  # thinking aloud is part of the telling
    await turns.on_turn("I cached the builds and we got to six minutes.", 5.0)
    assert said == [] and api.turns == []  # nothing goes to the coach during a take
    wall[0] = 75.0
    take, lines = coach.end_take()
    assert take == VoiceTake(
        text="Our deploys took forty minutes. Let me think. "
        "I cached the builds and we got to six minutes.",
        duration_s=75.0,
    )
    assert lines == [TAKE_DONE]
    assert coach.end_take() == (None, [])
    await turns.on_turn("How was that?")
    assert api.turns == ["How was that?"]  # back to the coach


async def test_co6_empty_and_cancelled_takes() -> None:
    coach, _, _ = make_coach()
    coach.start_take()
    assert coach.end_take() == (None, [TAKE_EMPTY])
    coach.start_take()
    await coach.on_candidate("First try.")
    assert coach.cancel_take() == [TAKE_CANCELLED]
    assert not coach.recording and coach.cancel_take() == []


async def test_co6_reconnect_repeats_the_coachs_last_line() -> None:
    coach, _, wall = make_coach()
    await coach.opening()
    await coach.on_candidate("Hi.")
    coach.on_disconnect()
    wall[0] = RECONNECT_S - 1
    assert not coach.reconnect_expired()
    assert coach.on_reconnect() == [WELCOME_BACK, "What was at stake?"]
    coach.on_disconnect()
    wall[0] += RECONNECT_S
    assert coach.reconnect_expired()


def test_co6_browser_messages() -> None:
    turn = json.loads(turn_message(["Hi."], {"ended": False}))
    assert turn == {"type": "coach_turn", "said": ["Hi."], "result": {"ended": False}}
    take = json.loads(take_message(VoiceTake("I led it.", 12.5)))
    assert take == {"type": "take_done", "text": "I led it.", "duration_s": 12.5}


def test_co6_audio_is_never_written() -> None:
    src = Path(coach_agent.__file__).parent
    for name in ("coach.py", "coach_agent.py", "coach_store.py"):
        assert not WRITES.search((src / name).read_text(encoding="utf-8")), name


# --- the API client -----------------------------------------------------------------------


def _api(handler: Any) -> ApiCoach:
    client = ApiCoach(AgentApiSettings(strong_internal_token="secret"))
    transport = httpx.MockTransport(handler)
    client._client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        base_url="http://api", transport=transport, headers={"X-Internal-Token": "secret"}
    )
    return client


async def test_co6_api_client_posts_the_turn_to_the_internal_endpoint() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/end"):
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"reply": {"message": "Why?"}, "ended": False})

    api = _api(handler)
    result = await api.turn(SID, "x" * 5000)
    assert result["reply"]["message"] == "Why?"
    assert seen[0].url.path == f"/internal/coach/sessions/{SID}/turns"
    assert seen[0].headers["X-Internal-Token"] == "secret"
    assert len(json.loads(seen[0].content)["text"]) == 4000  # the API's limit
    await api.end(SID)
    assert seen[1].url.path == f"/internal/coach/sessions/{SID}/end"


async def test_co6_api_client_errors() -> None:
    ended = _api(lambda r: httpx.Response(409, json={"detail": "ended"}))
    assert (await ended.turn(SID, "hi"))["ended"] is True
    slow = _api(lambda r: httpx.Response(504, json={"detail": "slow"}))
    with pytest.raises(CoachTurnError):
        await slow.turn(SID, "hi")

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(CoachTurnError):
        await _api(down).turn(SID, "hi")


# --- the database -------------------------------------------------------------------------

Maker = async_sessionmaker[AsyncSession]


@pytest.fixture
async def maker() -> AsyncIterator[Maker]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        tables = [Base.metadata.tables["coach_sessions"], Base.metadata.tables["coach_turns"]]
        await conn.run_sync(Base.metadata.create_all, tables=tables)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _add_session(maker: Maker, channel: SessionChannel) -> CoachSession:
    org = uuid.uuid4()
    row = CoachSession(
        id=uuid.uuid4(),
        org_id=org,
        user_id=uuid.uuid4(),
        style=CoachStyle.GENTLE,
        channel=channel,
        status=CoachSessionStatus.ACTIVE,
        minutes=0,
    )
    async with maker() as db:
        db.add(row)
        for seq, (speaker, text) in enumerate(
            [
                (CoachSpeaker.COACH, "Hi."),
                (CoachSpeaker.CANDIDATE, "Hello."),
                (CoachSpeaker.COACH, OPENER),
            ],
            start=1,
        ):
            db.add(
                CoachTurn(
                    org_id=org,
                    coach_session_id=row.id,
                    seq=seq,
                    speaker=speaker,
                    text=text,
                    start_ms=0,
                    end_ms=0,
                )
            )
        await db.commit()
    return row


async def test_co6_load_coach_session(maker: Maker) -> None:
    row = await _add_session(maker, SessionChannel.VOICE)
    loaded = await load_coach_session(maker, row.id)
    assert loaded is not None and loaded.org_id == row.org_id and loaded.opener == OPENER
    text = await _add_session(maker, SessionChannel.TEXT)
    assert await load_coach_session(maker, text.id) is None  # a text session has no voice room
    assert await load_coach_session(maker, uuid.uuid4()) is None


# --- the agent on the voice loop, with the fake STT and TTS -------------------------------


@pytest.fixture
def fake() -> ModelGateway:
    return build_gateway(Settings(model_profile="fake"))


async def test_co6_coach_agent_on_the_voice_loop_with_fake_stt_and_tts(
    fake: ModelGateway,
) -> None:
    """The fake STT transcribes the candidate, the coach answers, the fake TTS speaks it."""
    coach, api, _ = make_coach()
    sent: list[dict[str, Any]] = []
    ended: list[bool] = []

    async def notify(payload: bytes) -> None:
        sent.append(json.loads(payload))

    async def on_ended() -> None:
        ended.append(True)

    agent = CoachAgent(coach, on_ended, notify)
    stt = GatewaySTT(fake)
    async with AgentSession(stt=stt, tts=GatewayTTS(fake)) as session:
        await session.start(agent)
        await asyncio.sleep(0.05)
        assert agent.turns.stt is stt
        heard = await stt.recognize(rtc.AudioFrame(bytes(3200), 16000, 1, 1600))
        text = heard.alternatives[0].text
        await agent.turns.on_turn(text, 3.0)
        assert api.turns == [text]
        await coach.finish()
        await agent.speak([])
    assert sent[0] == {"type": "coach_turn", "said": [OPENER], "result": None}
    assert sent[1]["said"] == ["What was at stake?"]
    assert sent[1]["result"]["reply"]["message"] == "What was at stake?"
    assert ended == [True] and api.ends == 1
