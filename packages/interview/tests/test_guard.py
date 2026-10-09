"""The interviewer's output guard: reasoning leaks, feedback, wrong session length, repeats.

The bad replies are the real ones from the P13 AI-candidate run on the test server (behavioral,
Realistic, 30 minutes, text channel). The good replies must pass unchanged.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from strong_core.gateway import ModelGateway
from strong_core.gateway.types import Completion, Message
from strong_core.schemas import Phase, Speaker, Turn
from strong_interview import Interviewer, InterviewRunner, ListTraceSink, SessionController
from strong_interview.controller import DEFAULT_PLAN, Move, MoveKind
from strong_interview.guard import fallback_line, guard_reply, is_repeat
from strong_interview.testing import FakeClock, make_brief

PLAN_30 = list(DEFAULT_PLAN[30].values())

LEAK = (
    "The candidate asked how the team balances reliability with rapid expansion and keeps new "
    "payment methods isolated from card processing. The facts I have don't cover how the team "
    "structures services or deployments, so I should say I don't know that detail."
)
AGENDA_45 = (
    "Thanks, I'm glad to hear it. We'll spend about forty-five minutes on your past experience, "
    "how you approach real project situations, and then leave time for your questions."
)
RECORDS_Q = (
    "Can you tell me how many records were affected, and what your own part was in finding and "
    "fixing the duplicates?"
)
RECORDS_PROBE = (
    "Roughly how many records were affected, and how did you confirm the cleanup script fixed "
    "everything?"
)


def check(text: str, move: MoveKind = MoveKind.PROBE, **kw: Any) -> Any:
    kw.setdefault("duration_min", 30)
    kw.setdefault("plan_minutes", PLAN_30)
    return guard_reply(text, move, **kw)


# ---------------------------------------------------------------- meta (bug 1)


def test_reasoning_leak_is_not_spoken() -> None:
    result = check(LEAK, MoveKind.ANSWER_QUESTION)
    assert result.rules == ("meta",)
    assert result.text == ""
    assert not result.usable


@pytest.mark.parametrize(
    ("reply", "kept"),
    [
        ("The candidate wants to know about on-call. I'm afraid I don't know that detail.",
         "I'm afraid I don't know that detail."),
        ("Note: the facts don't say. Response: I'm not sure about that, sorry.",
         "I'm not sure about that, sorry."),
        ("My next move is to probe. What was your own part?", "What was your own part?"),
        ("Since pushback is on, I'll challenge that. Why not the simpler option?",
         "Why not the simpler option?"),
    ],
)  # fmt: skip
def test_meta_sentences_are_removed(reply: str, kept: str) -> None:
    result = check(reply)
    assert "meta" in result.rules
    assert result.text == kept


# ---------------------------------------------------------------- feedback (bug 3)


@pytest.mark.parametrize(
    ("move", "reply", "kept"),
    [
        (MoveKind.ASK,
         "Your last few answers have been quite detailed, so let's look at mentoring now. "
         "Tell me about a time you mentored someone.",
         "Let's look at mentoring now. Tell me about a time you mentored someone."),
        (MoveKind.WRAP_UP,
         "Thank you for your time today, and for the thoughtful answers. We'll be in touch.",
         "Thank you for your time today. We'll be in touch."),
        (MoveKind.PROBE, "Thanks, that makes the tradeoffs clear. How did you measure it?",
         "Thanks. How did you measure it?"),
        (MoveKind.PROBE, "That's a useful compromise. What if traffic doubled?",
         "What if traffic doubled?"),
        (MoveKind.PROBE, "Thanks, that's helpful detail on the refund launch. Who signed off?",
         "Thanks. Who signed off?"),
        (MoveKind.PROBE, "Thanks, that's clear on your mentoring work. What changed for them?",
         "Thanks. What changed for them?"),
        (MoveKind.PROBE, "That's a helpful start. What was your own part?",
         "What was your own part?"),
        (MoveKind.PROBE, "That's a fair point, but why not the simpler option?",
         "Why not the simpler option?"),
        (MoveKind.ANSWER_QUESTION, "That's a great question. The team is based in Dublin.",
         "The team is based in Dublin."),
        # From P13 run 20261008-164133-text-smoke-cf15 (Realistic mode).
        (MoveKind.PROBE, "You covered reconciliation well. How did you test the edge cases?",
         "How did you test the edge cases?"),
        (MoveKind.PROBE, "Your answer lays out the options clearly. Which one would you pick, and "
                         "why?",
         "Which one would you pick, and why?"),
        (MoveKind.PROBE, "You describe the Redis TTL and invalidation approach well. What happens "
                         "on a cache stampede?",
         "What happens on a cache stampede?"),
        (MoveKind.PROBE, "Kafka is a good tool for that, but I'm still not hearing your reasoning. "
                         "Why Kafka over a simple queue?",
         "I'm still not hearing your reasoning. Why Kafka over a simple queue?"),
        (MoveKind.PROBE, "Ease of setup is a fair point. What would change at ten times the load?",
         "What would change at ten times the load?"),
        (MoveKind.PROBE, "That beta approach sounds sensible. How did you decide who got access "
                         "first?",
         "How did you decide who got access first?"),
        (MoveKind.ASK, "Thanks for that candid answer. Let's move to a different topic. Tell me "
                       "about a time you disagreed with your manager.",
         "Let's move to a different topic. Tell me about a time you disagreed with your manager."),
    ],
)  # fmt: skip
def test_feedback_is_removed(move: MoveKind, reply: str, kept: str) -> None:
    result = check(reply, move)
    assert result.rules == ("feedback",)
    assert result.text == kept
    assert result.usable


# ---------------------------------------------------------------- good replies pass unchanged


@pytest.mark.parametrize(
    ("move", "reply"),
    [
        (MoveKind.GREET, "Hi, I'm Alex, and I'll be your interviewer today. Thanks for your time."),
        (MoveKind.SMALL_TALK, "Thanks, I'm glad to hear it. Did you have far to travel today?"),
        (MoveKind.ASK, "Can you give me a good example of a time when, under pressure, you "
                       "shipped something?"),
        (MoveKind.ASK, "Tell me about a strong example of ownership from your last role."),
        (MoveKind.ASK, "How did the move to Kubernetes go, and what was your part in it?"),
        (MoveKind.ASK, "What facts would you want before you decide?"),
        (MoveKind.ASK, "How do you decide when a candidate is ready for a senior role?"),
        (MoveKind.ASK, "Okay. How many records were affected, and what was your part?"),
        (MoveKind.PROBE, "Thanks. What did you measure to know it worked?"),
        (MoveKind.PROBE, "Why not the simpler option?"),
        (MoveKind.INVITE_QUESTIONS, "That covers my questions. What would you like to ask me?"),
        (MoveKind.ANSWER_QUESTION, "I'm afraid I don't know that detail."),
        (MoveKind.ANSWER_QUESTION, "The team owns the payments API and works mostly remote."),
        (MoveKind.WRAP_UP, "Thank you for your time today. The recruiter will be in touch soon."),
        (MoveKind.AGENDA, "We have about thirty minutes. I'll ask about your past projects, and "
                          "we'll keep about four minutes at the end for your questions."),
        (MoveKind.AGENDA, "We'll spend about twenty minutes on your experience, then you can "
                          "ask me anything."),
        (MoveKind.HINT, "Good start; think about who else the change affected."),
        # Near misses for the wider feedback rule: these must stay as they are.
        (MoveKind.PROBE, "You said you work well under pressure. What happened next?"),
        (MoveKind.PROBE, "How well did that design scale when traffic doubled?"),
        (MoveKind.ASK, "Tell me about a good tool you chose and why you chose it."),
        (MoveKind.ANSWER_QUESTION, "The team uses Kafka, which is a good fit for their event "
                                   "volume."),
        (MoveKind.PROBE, "I'm still not sure what your own part was. What did you personally do?"),
        (MoveKind.ASK, "Walk me through how you explained the trade-offs to your director."),
    ],
)  # fmt: skip
def test_good_replies_pass_unchanged(move: MoveKind, reply: str) -> None:
    result = check(reply, move)
    assert result.hits == ()
    assert result.text == reply


# ---------------------------------------------------------------- duration (bug 2)


def test_wrong_session_length_is_replaced() -> None:
    result = check(AGENDA_45, MoveKind.AGENDA)
    assert result.rules == ("duration",)
    assert "about thirty minutes on your past experience" in result.text
    assert "forty-five" not in result.text


@pytest.mark.parametrize(
    ("duration", "reply", "fixed"),
    [
        (10, "This 30-minute interview has a few questions.", "This 10-minute interview"),
        (45, "We have about an hour together.", "We have about forty-five minutes together."),
        (30, "We have Forty minutes today.", "We have Thirty minutes today."),
    ],
)
def test_other_wrong_lengths(duration: int, reply: str, fixed: str) -> None:
    result = check(
        reply, MoveKind.AGENDA, duration_min=duration, plan_minutes=DEFAULT_PLAN[duration].values()
    )
    assert result.rules == ("duration",)
    assert fixed in result.text


def test_mini_plan_minutes_are_allowed() -> None:
    reply = "This is a ten-minute interview: about eight minutes of questions, then we close."
    result = check(reply, MoveKind.AGENDA, duration_min=10, plan_minutes=DEFAULT_PLAN[10].values())
    assert result.hits == ()


# ---------------------------------------------------------------- repeat (bug 4)


def test_probe_after_a_dodge_is_not_a_repeat() -> None:
    """The case from the test server: a fair follow-up after an evasive answer."""
    assert not is_repeat(RECORDS_PROBE, RECORDS_Q)
    assert check(RECORDS_PROBE, previous=RECORDS_Q).usable


def test_near_verbatim_repeat_is_rejected() -> None:
    again = RECORDS_Q.replace("your own part", "your part")
    result = check(again, previous=RECORDS_Q)
    assert result.rules == ("repeat",)
    assert not result.usable
    assert check(again, MoveKind.REDO, previous=RECORDS_Q).usable  # redo repeats on purpose


def test_fallback_lines_are_clean() -> None:
    for move in MoveKind:
        line = fallback_line(move, name="Alex", duration_min=30, mini=False, question="Why?")
        result = check(line, move)
        assert result.hits == (), (move, line)
    mini = fallback_line(MoveKind.AGENDA, name="A", duration_min=10, mini=True, question=None)
    assert "ten-minute" in mini and "your questions" not in mini


# ---------------------------------------------------------------- the interviewer and traces


class Scripted:
    """The fake gateway, with the interviewer's spoken replies given by the test."""

    def __init__(self, gateway: ModelGateway, replies: list[str | Exception]) -> None:
        self._gateway = gateway
        self.replies = list(replies)
        self.sent: list[list[Message]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._gateway, name)

    async def complete(self, role: Any, messages: list[Message], **kw: Any) -> Any:
        if kw.get("output_type") is not None or not self.replies:
            return await self._gateway.complete(role, messages, **kw)
        self.sent.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        refs = tuple(m.prompt_ref for m in messages if m.prompt_ref)
        return Completion(output=reply, role=role, model="fake", profile="fake", prompt_refs=refs)


def _turn(text: str) -> Turn:
    return Turn(speaker=Speaker.INTERVIEWER, phase=Phase.CORE, text=text, start_ms=0, end_ms=1)


async def test_leak_gets_one_retry_with_a_stricter_prompt(gateway: ModelGateway) -> None:
    brief = make_brief()
    scripted = Scripted(gateway, [LEAK, "I'm afraid I don't know that detail."])
    interviewer = Interviewer(scripted, brief)  # type: ignore[arg-type]
    move = Move(MoveKind.ANSWER_QUESTION, Phase.CANDIDATE_QUESTIONS)
    said = await interviewer.say(move, [])
    assert said == "I'm afraid I don't know that detail."
    assert len(scripted.sent) == 2
    assert scripted.sent[1][-1].prompt_ref == "interviewer/turn_retry.v1"
    guards = [c.guard for c in interviewer.last_calls]
    assert [g["action"] for g in guards if g] == ["retry", "none"]


async def test_second_bad_reply_falls_back_to_a_fixed_line(gateway: ModelGateway) -> None:
    brief = make_brief()
    scripted = Scripted(gateway, [LEAK, LEAK])
    interviewer = Interviewer(scripted, brief)  # type: ignore[arg-type]
    said = await interviewer.say(Move(MoveKind.ANSWER_QUESTION, Phase.CANDIDATE_QUESTIONS), [])
    assert said == fallback_line(
        MoveKind.ANSWER_QUESTION, name="Alex", duration_min=30, mini=False, question=None
    )
    assert [c.guard["action"] for c in interviewer.last_calls if c.guard] == ["retry", "fallback"]


async def test_failed_retry_falls_back(gateway: ModelGateway) -> None:
    brief = make_brief()
    question = brief.questions[0]
    scripted = Scripted(gateway, [f"The candidate said nothing. {question.text}", RuntimeError()])
    interviewer = Interviewer(scripted, brief)  # type: ignore[arg-type]
    # The first reply keeps the question, so it is usable without a retry.
    said = await interviewer.say(Move(MoveKind.ASK, Phase.CORE, question), [])
    assert said == question.text
    scripted.replies = [RECORDS_Q, RuntimeError("provider down")]
    said = await interviewer.say(Move(MoveKind.PROBE, Phase.CORE, question), [_turn(RECORDS_Q)])
    assert said == fallback_line(
        MoveKind.PROBE, name="Alex", duration_min=30, mini=False, question=question.text
    )
    assert interviewer.last_calls[-1].error is not None


async def test_repeat_of_previous_question_is_asked_again_in_new_words(
    gateway: ModelGateway,
) -> None:
    brief = make_brief()
    scripted = Scripted(gateway, [RECORDS_Q, RECORDS_PROBE])
    interviewer = Interviewer(scripted, brief)  # type: ignore[arg-type]
    move = Move(MoveKind.PROBE, Phase.CORE, brief.questions[0])
    assert await interviewer.say(move, [_turn(RECORDS_Q)]) == RECORDS_PROBE


@pytest.mark.parametrize("duration", [10, 30, 45])
def test_agenda_prompt_has_the_real_duration(gateway: ModelGateway, duration: int) -> None:
    brief = make_brief(duration=duration)
    interviewer = Interviewer(gateway, brief)
    user = interviewer.turn_messages(Move(MoveKind.AGENDA, Phase.AGENDA), [])[-1].content
    assert f"Session length: {duration} minutes." in user
    core = DEFAULT_PLAN[duration][Phase.CORE]
    assert f"about {core} minutes of questions" in user.lower()
    if duration == 10:
        assert "mini interview" in user and "no separate time" in user
    else:
        assert "minutes for the candidate's questions" in user


async def test_guard_result_is_in_the_trace(gateway: ModelGateway, clock: FakeClock) -> None:
    brief = make_brief()
    scripted = Scripted(gateway, ["Hello, I'm Alex. Thanks for coming.", "Glad you could make it.",
                                  AGENDA_45])  # fmt: skip
    sink = ListTraceSink()
    runner = InterviewRunner(
        SessionController(brief, clock),
        Interviewer(scripted, brief),  # type: ignore[arg-type]
        trace=sink,
    )
    await runner.open()
    clock.advance(ms=20_000)
    await runner.respond("Hi!")
    clock.advance(ms=20_000)
    await runner.respond("Good, thanks.")  # the agenda, then the first question
    agenda = next(r for r in sink.records if r.move == "agenda")
    assert agenda.reason["guard"]["rules"] == ["duration"]
    assert agenda.reason["guard"]["action"] == "fixed"
    assert agenda.raw_reply == AGENDA_45
    assert agenda.spoken_text and "thirty minutes" in agenda.spoken_text


async def test_retry_is_traced_as_two_records(gateway: ModelGateway, clock: FakeClock) -> None:
    brief = make_brief()
    sink = ListTraceSink()
    scripted = Scripted(gateway, [LEAK, "Hello, I'm Alex. Thanks for your time."])
    runner = InterviewRunner(
        SessionController(brief, clock),
        Interviewer(scripted, brief),  # type: ignore[arg-type]
        trace=sink,
    )
    await runner.open()
    first, second = sink.records
    assert (first.call, first.move, second.move) == ("say", "greet", "greet")
    assert first.reason["guard"]["action"] == "retry" and first.spoken_text is None
    assert first.raw_reply == LEAK
    assert second.spoken_text == "Hello, I'm Alex. Thanks for your time."
    assert first.turn_index == second.turn_index == 0


async def test_overlapping_turns_are_answered_one_at_a_time(
    gateway: ModelGateway, clock: FakeClock
) -> None:
    """Two overlapping turns are not answered at the same time: each candidate turn gets its own
    reply, in order. The text API answers an overlapping turn with 409 (see the API tests)."""
    release = asyncio.Event()

    class Slow(Scripted):
        async def complete(self, role: Any, messages: list[Message], **kw: Any) -> Any:
            await release.wait()
            return await super().complete(role, messages, **kw)

    brief = make_brief()
    slow = Slow(gateway, ["How are you today?", "Did you travel far?", "Fine, thanks."])
    runner = InterviewRunner(SessionController(brief, clock), Interviewer(slow, brief))  # type: ignore[arg-type]
    release.set()
    await runner.open()
    release.clear()
    first = asyncio.create_task(runner.respond("Hi!"))
    second = asyncio.create_task(runner.respond("Hello again!"))
    await asyncio.sleep(0)
    assert runner.busy
    release.set()
    await asyncio.gather(first, second)
    assert not runner.busy
    speakers = [t.speaker for t in runner.turns]
    assert speakers[:3] == [Speaker.INTERVIEWER, Speaker.CANDIDATE, Speaker.INTERVIEWER]
    assert speakers[3] == Speaker.CANDIDATE
