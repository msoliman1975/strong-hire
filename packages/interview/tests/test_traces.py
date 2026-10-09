"""Interviewer traces (R2): the runner writes one record per model call, with move and reason."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest

from strong_core.gateway import ModelGateway, TokenUsage
from strong_core.gateway.prices import cost_usd, load_token_prices
from strong_core.schemas import Difficulty, Phase, ProbeDecision
from strong_interview import (
    PROBE_LIMIT,
    Interviewer,
    InterviewRunner,
    ListTraceSink,
    SessionController,
    TraceRecord,
)
from strong_interview.testing import FakeClock, make_brief
from strong_interview.trace_store import SqlTraceSink

ANSWER = "We built a new billing service and it went well."


def make_runner(
    gateway: ModelGateway, clock: FakeClock, sink: Any, **brief_args: Any
) -> InterviewRunner:
    brief = make_brief(**brief_args)
    return InterviewRunner(SessionController(brief, clock), Interviewer(gateway, brief), trace=sink)


async def test_r2_each_model_call_is_traced_with_move_and_timer(
    gateway: ModelGateway, clock: FakeClock
) -> None:
    sink = ListTraceSink()
    runner = make_runner(gateway, clock, sink)
    await runner.open()
    greet = sink.records[0]
    assert (greet.call, greet.move, greet.phase) == ("say", "greet", Phase.INTRO)
    assert greet.reason["why"] == ["start"]
    assert greet.turn_index == 0 and greet.seq == 1
    assert greet.phase_deadline_ms == runner.controller.deadline_ms(Phase.INTRO)
    assert greet.messages and greet.messages[0]["role"] == "system"
    assert greet.messages[-1]["role"] == "user"
    assert greet.raw_reply and greet.spoken_text == runner.turns[0].text
    assert greet.model and "interviewer/turn" in ",".join(greet.prompt_refs)
    assert greet.latency_ms is not None and greet.latency_ms >= 0

    clock.advance(ms=20_000)
    await runner.respond("Happy to be here.")  # small talk
    clock.advance(ms=20_000)
    await runner.respond("Sounds good.")  # agenda + first question
    moves = [r.move for r in sink.records]
    assert moves == ["greet", "small_talk", "agenda", "ask"]
    ask = sink.records[-1]
    assert ask.reason["why"] == ["next_phase", "next_question"]
    assert ask.question_ref == "q1"


async def test_r2_decide_and_probe_carry_the_probe_decision(
    gateway: ModelGateway, clock: FakeClock
) -> None:
    sink = ListTraceSink()
    runner = make_runner(gateway, clock, sink)
    await runner.open()
    await runner.respond("Happy to be here.")
    await runner.respond("Sounds good.")
    clock.advance(ms=30_000)
    await runner.respond(ANSWER)
    decide, probe = sink.records[-2:]
    assert decide.call == "decide" and decide.move == "decide"
    assert decide.reason["decision"] == {"action": "probe", "missing": ["measurable_result"]}
    assert decide.raw_reply and "probe" in decide.raw_reply
    assert decide.question_ref == "q1"
    assert probe.call == "say" and probe.move == "probe"
    assert probe.reason["why"] == ["model_chose_probe"]
    assert probe.reason["missing"] == ["measurable_result"]
    assert probe.reason["decision"]["action"] == "probe"
    assert probe.reason["probes_used"] == 1  # this probe counted
    assert probe.reason["probe_limit"] == PROBE_LIMIT[Difficulty.REALISTIC]


async def test_r2_moving_on_at_the_probe_limit_says_why(
    gateway: ModelGateway, clock: FakeClock
) -> None:
    """The fake model always probes, so the controller moves on when the limit is reached."""
    sink = ListTraceSink()
    runner = make_runner(gateway, clock, sink, difficulty=Difficulty.FRIENDLY)
    await runner.open()
    await runner.respond("Hi.")
    await runner.respond("Sounds good.")
    for _ in range(PROBE_LIMIT[Difficulty.FRIENDLY] + 1):
        clock.advance(ms=30_000)
        await runner.respond(ANSWER)
    nxt = sink.records[-1]
    assert nxt.move in ("ask", "curveball")
    assert nxt.reason["why"][0] == "probe_limit_reached"
    # No decide call is made once the limit is reached.
    assert sink.records[-2].call == "say"


async def test_r2_core_time_up_is_the_reason(gateway: ModelGateway, clock: FakeClock) -> None:
    sink = ListTraceSink()
    runner = make_runner(gateway, clock, sink)
    await runner.open()
    await runner.respond("Hi.")
    await runner.respond("Sounds good.")
    clock.advance(minutes=30)  # past the CORE deadline and the session
    await runner.respond(ANSWER)
    last = sink.records[-1]
    assert last.move == "wrap_up"
    assert last.reason["why"] == ["session_time_up"]


async def test_r2_failed_decision_is_traced_with_the_error(
    gateway: ModelGateway, clock: FakeClock
) -> None:
    class Broken:
        def __getattr__(self, name: str) -> Any:
            return getattr(gateway, name)

        async def complete(self, *args: Any, **kwargs: Any) -> Any:
            if kwargs.get("output_type") is ProbeDecision:
                raise RuntimeError("bad JSON")
            return await gateway.complete(*args, **kwargs)

    sink = ListTraceSink()
    brief = make_brief()
    runner = InterviewRunner(
        SessionController(brief, clock),
        Interviewer(Broken(), brief),  # type: ignore[arg-type]
        trace=sink,
    )
    await runner.open()
    await runner.respond("Hi.")
    await runner.respond("Sounds good.")
    clock.advance(ms=30_000)
    await runner.respond(ANSWER)
    decide = next(r for r in sink.records if r.call == "decide")
    assert decide.error and "bad JSON" in decide.error
    assert decide.reason["decision"] == {"action": "move_on", "missing": []}
    after = sink.records[-1]
    assert after.reason["why"][0] == "model_chose_move_on"


async def test_r2_fixed_lines_and_rollback_are_traced(
    gateway: ModelGateway, clock: FakeClock
) -> None:
    sink = ListTraceSink()
    runner = make_runner(gateway, clock, sink)
    await runner.open()
    await runner.line("Sure, take your time.", kind="take_your_time")
    line = sink.records[-1]
    assert (line.call, line.move, line.spoken_text) == (
        "line",
        "take_your_time",
        "Sure, take your time.",
    )
    assert line.messages is None and line.input_tokens == 0
    checkpoint = runner.checkpoint()
    await runner.respond("Happy to be here.")
    runner.rollback(checkpoint)
    rollback = sink.records[-1]
    assert rollback.call == "rollback"
    assert rollback.reason == {"why": ["candidate_kept_talking"], "turns_taken_back": 2}
    runner.trace_line("welcome_back", "Welcome back.")
    assert sink.records[-1].move == "welcome_back"
    assert [r.seq for r in sink.records] == list(range(1, len(sink.records) + 1))


async def test_r2_a_broken_sink_never_breaks_the_interview(
    gateway: ModelGateway, clock: FakeClock
) -> None:
    class Broken:
        def write(self, record: TraceRecord) -> None:
            raise RuntimeError("database down")

    runner = make_runner(gateway, clock, Broken())
    turns = await runner.open()
    assert turns and turns[0].text
    assert await runner.respond("Hi.")


async def test_r2_no_sink_means_no_traces(gateway: ModelGateway, clock: FakeClock) -> None:
    runner = make_runner(gateway, clock, None)
    await runner.open()
    assert runner.trace is None and runner.turns


def test_r2_prices_come_from_the_litellm_config(tmp_path: Path) -> None:
    (tmp_path / "litellm.p.yaml").write_text(
        "model_list:\n"
        "  - model_name: fast\n"
        "    model_info: {input_cost_per_token: 0.000001, output_cost_per_token: 0.000004}\n"
        "  - model_name: stt\n"
        "    model_info: {mode: audio_transcription}\n",
        encoding="utf-8",
    )
    load_token_prices.cache_clear()
    usage = TokenUsage(input_tokens=1000, output_tokens=100)
    assert cost_usd("p", "fast", usage, tmp_path) == 0.0014
    assert cost_usd("p", "stt", usage, tmp_path) is None
    assert cost_usd("missing", "fast", usage, tmp_path) is None


async def test_r2_moving_on_after_the_same_gap_says_why(
    gateway: ModelGateway, clock: FakeClock
) -> None:
    """The fake model probes for the same gap every time: the second time the controller moves
    on, and the trace says why (same_gap_not_filled)."""
    sink = ListTraceSink()
    runner = make_runner(gateway, clock, sink)  # Realistic: 2 probes allowed
    await runner.open()
    for _ in range(5):
        clock.advance(ms=20_000)
        await runner.respond(ANSWER)
    says = [r for r in sink.records if r.call == "say"]
    asks = [r for r in says if r.move == "ask"]
    assert any("same_gap_not_filled" in r.reason["why"] for r in asks)


async def test_r2_a_stuck_trace_insert_gives_up_and_frees_the_lock(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A trace insert that cannot get the lock (or the database) in time is logged and dropped,
    and `flush` with a limit returns instead of waiting forever."""

    def no_database() -> Any:
        raise AssertionError("the insert must not reach the database while the lock is held")

    sink = SqlTraceSink(no_database, uuid.uuid4(), uuid.uuid4(), timeout_s=0.05)  # type: ignore[arg-type]
    record = TraceRecord(
        seq=1,
        turn_index=0,
        call="line",
        move="x",
        reason={},
        phase=Phase.INTRO,
        elapsed_ms=0,
        phase_deadline_ms=0,
    )
    async with sink.lock:  # someone else holds the lock and never lets go in time
        sink.write(record)
        assert await sink.flush(timeout_s=0.01) is False
        await asyncio.sleep(0.1)
        assert await sink.flush(timeout_s=1) is True
    assert not sink.lock.locked()
    assert "trace 1 of session" in caplog.text and "not saved" in caplog.text
