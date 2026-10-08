"""Voice turn taking: one reply at a time, words merged when the candidate goes on talking, and
requests for time to think."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from strong_voice.interview import CHECK_IN, TAKE_YOUR_TIME
from strong_voice.turns import CandidateTurns, is_thinking_request


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


def make_turns(
    interview: FakeInterview, *, think: float = 60.0, resume: float = 0.05
) -> tuple[CandidateTurns, list[str]]:
    said: list[str] = []

    async def speak(lines: list[str]) -> None:
        said.extend(lines)

    return CandidateTurns(interview, speak, thinking_wait_s=think, resume_wait_s=resume), said


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
