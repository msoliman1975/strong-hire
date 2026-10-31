"""The voice interview without LiveKit (P7): transcript, end of session, Coach, reconnect (IV-9)."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from strong_core.config import ModelProfile, Settings
from strong_core.gateway import UsageRecord, build_gateway, set_usage_sink, usage_context
from strong_core.schemas import Difficulty, Mode, Phase, Speaker, Turn
from strong_interview import CoachNotAllowedError, Interviewer, InterviewRunner, SessionController
from strong_interview.testing import CUSTOM_MUST_ASK, FakeClock, make_brief, make_custom_brief
from strong_voice import interview as interview_module
from strong_voice.interview import RECONNECT_S, TAKE_YOUR_TIME, WELCOME_BACK, VoiceInterview
from strong_voice.session_store import session_id_from_room

SID = uuid.uuid4()
WRITES = re.compile(r"open\([^)]*['\"]w|write_bytes|\.wav|wave\.open|AudioFrame\(")


@dataclass
class FakeStore:
    turns: list[Turn] = field(default_factory=list)
    prompt_version: str | None = None

    async def save_turn(self, session_id: uuid.UUID, turn: Turn) -> None:
        assert session_id == SID
        self.turns.append(turn)

    async def save_provenance(self, session_id: uuid.UUID, prompt_version: str | None) -> None:
        self.prompt_version = prompt_version


@dataclass
class FakeFinisher:
    calls: list[bool] = field(default_factory=list)

    async def finish(self, session_id: uuid.UUID, *, interrupted: bool) -> None:
        self.calls.append(interrupted)


@dataclass
class Rig:
    voice: VoiceInterview
    store: FakeStore
    finisher: FakeFinisher
    clock: FakeClock
    wall: list[float]


def make_rig(
    mode: Mode = Mode.REALISTIC, difficulty: Difficulty = Difficulty.FRIENDLY, custom: bool = False
) -> Rig:
    clock = FakeClock()
    wall = [0.0]
    brief = (
        make_custom_brief(mode=mode, difficulty=difficulty)
        if custom
        else make_brief(mode=mode, difficulty=difficulty, questions=6)
    )
    gateway = build_gateway(Settings(model_profile=ModelProfile.FAKE))
    runner = InterviewRunner(SessionController(brief, clock), Interviewer(gateway, brief))
    store, finisher = FakeStore(), FakeFinisher()
    voice = VoiceInterview(SID, runner, store, finisher, now=lambda: wall[0])
    return Rig(voice, store, finisher, clock, wall)


async def test_opening_is_spoken_and_saved() -> None:
    rig = make_rig()
    lines = await rig.voice.opening()
    assert len(lines) == 1 and lines[0]
    assert [t.phase for t in rig.store.turns] == [Phase.INTRO]


async def test_candidate_turn_is_saved_with_its_timing() -> None:
    rig = make_rig()
    await rig.voice.opening()
    rig.clock.advance(ms=30_000)
    lines = await rig.voice.on_candidate("Happy to be here.", spoken_s=4.0)
    assert lines  # small talk
    candidate = rig.store.turns[1]
    assert candidate.speaker == Speaker.CANDIDATE and candidate.text == "Happy to be here."
    assert candidate.end_ms - candidate.start_ms == 4_000
    assert await rig.voice.on_candidate("   ") == []  # silence is not a turn


async def test_iv7_session_ends_once_with_provenance() -> None:
    """The controller ends the session; the agent then ends it in the API once (FB-3)."""
    rig = make_rig()
    await rig.voice.opening()
    for _ in range(60):
        if rig.voice.ended:
            break
        rig.clock.advance(ms=20_000)
        phase = rig.voice.runner.controller.phase
        answer = "No questions, thanks." if phase == Phase.CANDIDATE_QUESTIONS else "I led it."
        await rig.voice.on_candidate(answer, spoken_s=10.0)
    assert rig.voice.ended
    assert rig.finisher.calls == [False]
    await rig.voice.finish(interrupted=True)  # safe to call again
    assert rig.finisher.calls == [False]
    assert rig.store.prompt_version and "interviewer/turn" in rig.store.prompt_version
    assert rig.store.turns == rig.voice.runner.turns  # every turn saved
    assert rig.store.turns[-1].phase == Phase.WRAP_UP


async def test_iv8_coach_commands() -> None:
    realistic = make_rig(mode=Mode.REALISTIC)
    await realistic.voice.opening()
    with pytest.raises(CoachNotAllowedError):
        await realistic.voice.coach("hint")
    coach = make_rig(mode=Mode.COACH)
    await coach.voice.opening()
    await coach.voice.on_candidate("Thanks.")
    await coach.voice.on_candidate("Sounds good.")  # agenda + first question
    hint = await coach.voice.coach("hint")
    assert len(hint) == 1
    assert await coach.voice.coach("pause") == []
    assert coach.voice.runner.controller.paused
    assert await coach.voice.coach("resume") == []


async def test_iv9_reconnect_in_time_goes_on_at_the_same_question() -> None:
    """IV-9: back within 2 minutes: the clock did not run, and the last question is repeated."""
    rig = make_rig()
    await rig.voice.opening()
    await rig.voice.on_candidate("Thanks.")
    await rig.voice.on_candidate("Sounds good.")  # agenda + first question
    question = rig.voice.runner.turns[-1]
    elapsed = rig.voice.runner.controller.elapsed_ms
    rig.voice.on_disconnect()
    rig.clock.advance(minutes=1)
    rig.wall[0] += 60
    assert not rig.voice.reconnect_expired()
    lines = rig.voice.on_reconnect()
    assert lines == [WELCOME_BACK, question.text]
    assert rig.voice.runner.controller.elapsed_ms == elapsed  # time away is not counted
    assert rig.voice.runner.controller.question is not None
    assert rig.voice.runner.controller.question.id == question.question_ref
    assert rig.finisher.calls == []


async def test_cu4_iv9_custom_voice_session_keeps_must_ask_state_over_a_reconnect() -> None:
    """CU-4, IV-9: a Custom voice session goes through the same controller. A reconnect keeps
    the must-ask questions left, the verbatim question is spoken unchanged, and every must-ask
    question is asked before the candidate's questions."""
    rig = make_rig(custom=True)
    await rig.voice.opening()
    await rig.voice.on_candidate("Thanks.")
    lines = await rig.voice.on_candidate("Sounds good.")  # agenda + own1 (verbatim)
    assert lines is not None
    own1 = next(q for q in rig.voice.runner.controller.brief.questions if q.id == "own1")
    assert lines[-1].endswith(own1.text)
    ctl = rig.voice.runner.controller
    assert ctl.must_ask_left == ["own2", "own3"]
    rig.voice.on_disconnect()
    rig.clock.advance(minutes=1)
    rig.wall[0] += 60
    assert rig.voice.on_reconnect()[0] == WELCOME_BACK
    assert ctl.must_ask_left == ["own2", "own3"]
    rig.clock.advance(minutes=24)  # past the CORE time: the must-ask questions still come
    for _ in range(20):
        if ctl.phase != Phase.CORE:
            break
        await rig.voice.on_candidate("We shipped it on time.")
    assert ctl.phase == Phase.CANDIDATE_QUESTIONS
    refs = {t.question_ref for t in rig.store.turns if t.question_ref}
    assert set(CUSTOM_MUST_ASK) <= refs


async def test_iv9_no_reconnect_ends_the_session_as_interrupted() -> None:
    rig = make_rig()
    await rig.voice.opening()
    rig.voice.on_disconnect()
    rig.wall[0] += RECONNECT_S
    assert rig.voice.reconnect_expired()
    await rig.voice.finish(interrupted=True)
    assert rig.finisher.calls == [True]
    assert rig.voice.ended
    assert rig.voice.on_reconnect() == []  # too late


async def test_finish_survives_an_api_error() -> None:
    rig = make_rig()

    class Broken:
        async def finish(self, session_id: uuid.UUID, *, interrupted: bool) -> None:
            raise RuntimeError("api down")

    rig.voice.finisher = Broken()
    await rig.voice.opening()
    await rig.voice.finish(interrupted=False)  # logged, not raised
    assert rig.voice.ended


def test_audio_is_never_written() -> None:
    """Spec: audio is never stored. The interview code saves text only, and writes no files."""
    src = Path(interview_module.__file__).parent
    for name in ("interview.py", "session_store.py", "interview_agent.py"):
        text = (src / name).read_text(encoding="utf-8")
        assert not WRITES.search(text), name
    fields = {"speaker", "phase", "text", "start_ms", "end_ms", "question_ref"}
    assert set(Turn.model_fields) == fields


def test_session_room_names() -> None:
    sid = uuid.uuid4()
    assert session_id_from_room(f"session-{sid}") == sid
    assert session_id_from_room("latency-local-1-abcd") is None
    assert session_id_from_room("session-not-a-uuid") is None


async def test_state_message_for_the_browser() -> None:
    from strong_voice.interview_agent import state_message

    rig = make_rig(mode=Mode.COACH)
    lines = await rig.voice.opening()
    await rig.voice.coach("pause")
    message = json.loads(state_message(rig.voice, lines))
    assert message == {
        "type": "state",
        "phase": "intro",
        "paused": True,
        "elapsed_ms": rig.voice.runner.controller.elapsed_ms,
        "prep_ms_left": None,
        "question": None,
        "questions": None,
        "said": lines,
    }


async def test_sv6_state_message_counts_the_core_questions() -> None:
    """SV-6: in the core phase the browser gets the question asked and how many are planned."""
    from strong_voice.interview_agent import state_message

    rig = make_rig(mode=Mode.COACH)
    await rig.voice.opening()
    controller = rig.voice.runner.controller
    queued = len(controller._queue)
    controller.phase = Phase.CORE
    controller.asked = ["q1", "q2"]
    message = json.loads(state_message(rig.voice, []))
    assert message["question"] == 2
    assert message["questions"] == 2 + queued
    assert controller.questions_planned == 2 + queued


def test_iv10_agent_tells_the_browser_how_the_voice_sounds() -> None:
    """IV-10: the live page picks the interviewer face from this attribute."""
    from strong_voice.interview_agent import INTERVIEWER_VOICE_ATTRIBUTE, interviewer_attributes

    assert interviewer_attributes() == {INTERVIEWER_VOICE_ATTRIBUTE: "female"}  # the fake TTS


async def test_voice_interview_takes_back_and_keeps_the_question_open() -> None:
    """With the real runner (fake model): a taken-back reply leaves no trace, and a request for
    time saves both lines without moving on."""
    rig = make_rig()
    await rig.voice.opening()
    for _ in range(4):
        rig.clock.advance(ms=60_000)
        await rig.voice.on_candidate("We built a billing service and I led it.", 5.0)
    controller = rig.voice.runner.controller
    assert controller.phase == Phase.CORE
    saved = len(rig.store.turns)
    state = controller.snapshot()

    assert (
        await rig.voice.on_candidate("Yeah, great question.", 2.0, superseded=lambda: True) is None
    )
    assert len(rig.store.turns) == saved and controller.snapshot() == state

    lines = await rig.voice.on_thinking("Give me a moment.", 1.0)
    assert lines == [TAKE_YOUR_TIME]
    assert [t.speaker for t in rig.store.turns[saved:]] == [Speaker.CANDIDATE, Speaker.INTERVIEWER]
    assert controller.snapshot() == state


async def test_iv11_prep_time_stops_the_clock_in_realistic_mode_too() -> None:
    """IV-11: prep time is allowed in every mode, and the interview clock stops during it."""
    from strong_voice.interview import PREP_OVER, prep_line

    rig = make_rig(mode=Mode.REALISTIC)
    await rig.voice.opening()
    rig.clock.advance(ms=30_000)
    lines = await rig.voice.start_prep(3, "Could I have three minutes to prepare?", spoken_s=2.0)
    assert lines == [prep_line(3)]
    assert rig.voice.preparing and rig.voice.prep_ms_left() == 180_000
    elapsed = rig.voice.runner.controller.elapsed_ms
    rig.clock.advance(minutes=3)
    rig.wall[0] += 180
    assert rig.voice.runner.controller.elapsed_ms == elapsed  # prep is not interview time
    assert rig.voice.prep_ms_left() == 0
    assert await rig.voice.end_prep(timed_out=True) == [PREP_OVER]
    rig.clock.advance(ms=10_000)
    assert rig.voice.runner.controller.elapsed_ms == elapsed + 10_000
    speakers = [t.speaker for t in rig.store.turns[-3:]]
    assert speakers == [Speaker.CANDIDATE, Speaker.INTERVIEWER, Speaker.INTERVIEWER]


async def test_iv11_prep_is_capped_at_three_minutes_and_ends_once() -> None:
    rig = make_rig()
    await rig.voice.opening()
    await rig.voice.start_prep(10)
    assert rig.voice.prep_ms_left() == 180_000
    assert await rig.voice.start_prep(1) == []  # already preparing
    assert await rig.voice.end_prep(say=False) == []
    assert await rig.voice.end_prep() == []  # not preparing any more
    assert not rig.voice.preparing


async def test_ob2_voice_usage_comes_from_the_gateway_once_per_call() -> None:
    """OB-2: inside the session's usage context every interviewer call reports a row with its
    role; the end of the session writes no rows of its own (nothing is counted twice)."""
    records: list[UsageRecord] = []

    async def sink(record: UsageRecord) -> None:
        records.append(record)

    previous = set_usage_sink(sink)
    org = uuid.uuid4()
    try:
        rig = make_rig()
        with usage_context(org, session_id=SID):
            await rig.voice.opening()
            rig.clock.advance(ms=30_000)
            await rig.voice.on_candidate("Happy to be here.", spoken_s=4.0)
        calls = len(records)
        await rig.voice.finish(interrupted=False)
    finally:
        set_usage_sink(previous)
    assert calls > 0 and len(records) == calls
    assert {(r.role.value, r.org_id, r.session_id) for r in records} == {("interviewer", org, SID)}
