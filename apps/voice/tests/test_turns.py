"""Voice turn taking: one reply at a time, words merged when the candidate goes on talking, and
requests for time to think."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from strong_voice.interview import CHECK_IN, PREP_OVER, PREP_READY, TAKE_YOUR_TIME, prep_line
from strong_voice.turns import CandidateTurns, is_ready, is_thinking_request, prep_request_minutes


@pytest.mark.parametrize(
    "text",
    [
        "Yeah, give me like 30 seconds to organize my thoughts.",
        "Let me think about that.",
        "Hmm, one moment please.",
        "Can I take a minute?",
        "Hold on.",
        "Okay, let me gather my thoughts.",
    ],
)
def test_thinking_requests(text: str) -> None:
    assert is_thinking_request(text)


@pytest.mark.parametrize(
    "text",
    [
        "Yeah, this is a great question Alex.",
        "So, basically...",
        "It was very easy.",
        # A long answer that mentions minutes is an answer, not a request.
        "We cut the build from forty minutes to six by caching the dependencies, and I owned "
        "the rollout across four teams, which took a few minutes of downtime each week.",
    ],
)
def test_not_thinking_requests(text: str) -> None:
    assert not is_thinking_request(text)


@dataclass
class FakeInterview:
    """Records calls. `hold` makes on_candidate wait, as a slow model reply would."""

    hold: asyncio.Event | None = None
    calls: list[str] = field(default_factory=list)
    thinking: list[str] = field(default_factory=list)
    check_ins: int = 0
    prep: list[int] = field(default_factory=list)
    prep_ended: list[str] = field(default_factory=list)
    preparing: bool = False

    async def on_candidate(
        self, text: str, spoken_s: float | None = None, superseded: Callable[[], bool] | None = None
    ) -> list[str] | None:
        self.calls.append(text)
        if self.hold is not None:
            await self.hold.wait()
            self.hold = None
        if superseded is not None and superseded():
            return None
        return [f"reply to: {text}"]

    async def on_thinking(self, text: str, spoken_s: float | None = None) -> list[str]:
        self.thinking.append(text)
        return [TAKE_YOUR_TIME]

    async def check_in(self) -> list[str]:
        self.check_ins += 1
        return [CHECK_IN]

    async def start_prep(
        self, minutes: int, text: str | None = None, spoken_s: float | None = None
    ) -> list[str]:
        self.prep.append(minutes)
        self.preparing = True
        return [prep_line(minutes)]

    async def end_prep(self, *, timed_out: bool = False, say: bool = True) -> list[str]:
        if not self.preparing:
            return []
        self.preparing = False
        self.prep_ended.append("timeout" if timed_out else "ready" if say else "answer")
        if not say:
            return []
        return [PREP_OVER if timed_out else PREP_READY]


def make_turns(
    interview: FakeInterview, *, think: float = 60.0, resume: float = 0.05, minute: float = 60.0
) -> tuple[CandidateTurns, list[str]]:
    said: list[str] = []

    async def speak(lines: list[str]) -> None:
        said.extend(lines)

    turns = CandidateTurns(
        interview, speak, thinking_wait_s=think, resume_wait_s=resume, minute_s=minute
    )
    return turns, said


async def test_one_turn_one_reply() -> None:
    interview = FakeInterview()
    turns, said = make_turns(interview)
    await turns.on_turn("I led the migration.", 3.0)
    assert said == ["reply to: I led the migration."]
    assert turns.pending == []


async def test_speaking_again_takes_the_reply_back_and_merges_the_words() -> None:
    """Session ab996192: "Yeah, this is a great question Alex." then "Actually, I..." got two
    separate replies. Now the first reply is not spoken, and both parts are answered together."""
    interview = FakeInterview(hold=asyncio.Event())
    turns, said = make_turns(interview)

    first = asyncio.create_task(turns.on_turn("Yeah, this is a great question Alex.", 2.0))
    await asyncio.sleep(0)
    turns.on_user_state("speaking")  # the candidate goes on while the reply is prepared
    assert interview.hold is not None
    interview.hold.set()
    await first
    assert said == [] and turns.taken_back == 1
    assert turns.pending == ["Yeah, this is a great question Alex."]

    turns.on_user_state("listening")
    await turns.on_turn("At eBay I coached one PM through a launch.", 4.0)
    merged = "Yeah, this is a great question Alex. At eBay I coached one PM through a launch."
    assert interview.calls[-1] == merged
    assert said == [f"reply to: {merged}"]


async def test_held_words_are_answered_when_no_next_turn_comes() -> None:
    """The candidate's sound was not speech (no new turn): the held words still get a reply."""
    interview = FakeInterview(hold=asyncio.Event())
    turns, said = make_turns(interview, resume=0.01)
    first = asyncio.create_task(turns.on_turn("I owned the rollout.", 2.0))
    await asyncio.sleep(0)
    turns.on_user_state("speaking")
    assert interview.hold is not None
    interview.hold.set()
    await first
    assert said == []

    turns.on_user_state("listening")
    await asyncio.sleep(0.05)
    assert said == ["reply to: I owned the rollout."]


class FakeSTT:
    """A transcriber that stays busy until `finish()` (a slow STT on the last segment)."""

    def __init__(self, *, busy: bool) -> None:
        self._idle = asyncio.Event()
        if not busy:
            self._idle.set()
        self.settles = 0

    @property
    def busy(self) -> bool:
        return not self._idle.is_set()

    def finish(self) -> None:
        self._idle.set()

    async def settled(self, quiet_s: float = 0.25, timeout_s: float = 15.0) -> bool:
        await self._idle.wait()
        self.settles += 1
        return True


async def test_iv1_reply_waits_for_the_rest_of_the_answer_from_a_slow_stt() -> None:
    """Session 5ff84450: the turn ended while the STT was still transcribing the rest of the
    answer, so the interviewer replied to the first sentence and then to the rest as a new turn.
    Now the reply waits, and the whole answer gets one reply."""
    interview = FakeInterview()
    stt = FakeSTT(busy=True)
    turns, said = make_turns(interview)
    turns.stt, turns.late_wait_s = stt, 0.05

    await turns.on_turn("When we wrapped up the rollout, I had to present it to our VP.", 40.0)
    await asyncio.sleep(0.02)
    assert said == [] and interview.calls == [] and turns.waited_for_stt == 1

    stt.finish()  # the rest arrives as the next turn
    await turns.on_turn("I framed it around conversion lift, and we got approval to expand.", 0.0)
    merged = (
        "When we wrapped up the rollout, I had to present it to our VP. "
        "I framed it around conversion lift, and we got approval to expand."
    )
    assert interview.calls == [merged]
    await asyncio.sleep(0.1)
    assert said == [f"reply to: {merged}"]  # one reply, not a second one from the timer


async def test_iv1_held_words_are_answered_when_the_late_transcript_is_empty() -> None:
    """The busy segment was noise (empty text, so no next turn): the words still get a reply."""
    interview = FakeInterview()
    stt = FakeSTT(busy=True)
    turns, said = make_turns(interview)
    turns.stt, turns.late_wait_s = stt, 0.01

    await turns.on_turn("I owned the rollout.", 2.0)
    assert said == []
    stt.finish()
    await asyncio.sleep(0.1)
    assert said == ["reply to: I owned the rollout."] and stt.settles == 1


async def test_iv1_no_wait_when_the_stt_is_idle() -> None:
    interview = FakeInterview()
    turns, said = make_turns(interview)
    turns.stt = FakeSTT(busy=False)
    await turns.on_turn("I led the migration.", 3.0)
    assert said == ["reply to: I led the migration."] and turns.waited_for_stt == 0


async def test_thinking_request_gets_one_line_then_one_check_in() -> None:
    interview = FakeInterview()
    turns, said = make_turns(interview, think=0.01)
    await turns.on_turn("Give me like 30 seconds to organize my thoughts.", 3.0)
    assert said == [TAKE_YOUR_TIME] and interview.calls == []
    await asyncio.sleep(0.05)
    assert said == [TAKE_YOUR_TIME, CHECK_IN] and interview.check_ins == 1


async def test_no_check_in_once_the_candidate_speaks() -> None:
    interview = FakeInterview()
    turns, said = make_turns(interview, think=0.02)
    await turns.on_turn("Let me think.", 1.0)
    turns.on_user_state("speaking")
    await asyncio.sleep(0.05)
    assert said == [TAKE_YOUR_TIME] and interview.check_ins == 0


# --------------------------------------------------------------------------- prep time (IV-11)


@pytest.mark.parametrize(
    ("text", "minutes"),
    [
        ("Can I take a minute?", 1),
        ("Could I have three minutes to prepare?", 3),
        ("Give me 2 minutes please.", 2),
        ("I need a few minutes.", 3),
        ("Give me 30 seconds.", None),
        ("We cut the build from 40 minutes to six.", None),
    ],
)
def test_iv11_prep_requests(text: str, minutes: int | None) -> None:
    assert prep_request_minutes(text) == minutes


@pytest.mark.parametrize(
    ("text", "ready"),
    [
        ("Okay, I'm ready.", True),
        ("Ready.", True),
        ("Alright, let's go.", True),
        ("I was ready to lead it.", False),
    ],
)
def test_iv11_ready_phrases(text: str, ready: bool) -> None:
    assert is_ready(text) is ready


async def test_iv11_spoken_request_starts_prep_and_the_timer_ends_it() -> None:
    interview = FakeInterview()
    turns, said = make_turns(interview, minute=0.01)
    await turns.on_turn("Could I have three minutes to prepare?", 2.0)
    assert interview.prep == [3] and said == [prep_line(3)]
    assert interview.thinking == [] and interview.calls == []  # not an answer, no check-in path
    await asyncio.sleep(0.08)
    assert interview.prep_ended == ["timeout"] and said[-1] == PREP_OVER


async def test_iv11_during_prep_thinking_aloud_is_ignored_and_ready_ends_it() -> None:
    interview = FakeInterview()
    turns, said = make_turns(interview)
    await turns.start_prep(1)  # the prep button
    await turns.on_turn("Hmm, okay, so first...", 1.0)
    assert interview.calls == [] and interview.preparing
    await turns.on_turn("Okay, I'm ready.", 1.0)
    assert interview.prep_ended == ["ready"] and said[-1] == PREP_READY
    turns.close()


async def test_iv11_a_real_answer_ends_prep_and_gets_a_reply() -> None:
    interview = FakeInterview()
    turns, said = make_turns(interview)
    await turns.start_prep(3)
    answer = "At eBay I led the checkout migration across four teams in one quarter."
    await turns.on_turn(answer, 5.0)
    assert interview.prep_ended == ["answer"]
    assert said[-1] == f"reply to: {answer}"


async def test_iv11_ready_button_ends_prep() -> None:
    interview = FakeInterview()
    turns, said = make_turns(interview)
    await turns.start_prep(1)
    await turns.ready()
    assert interview.prep_ended == ["ready"] and said == [prep_line(1), PREP_READY]
