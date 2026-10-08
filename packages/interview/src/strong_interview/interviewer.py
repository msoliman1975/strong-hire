"""Interviewer turn logic: what to say for each move, and the probe-or-move-on decision.

All model calls go through the gateway with the interviewer role, and all text comes from
prompts/interviewer/. Small-tier models get the small prompt variants (PL-5) and a shorter
turn window. The decision after an answer is a ProbeDecision, a constrained choice; if the
model fails to return one, the interviewer moves on.

Every spoken reply passes the output guard (strong_interview.guard): reasoning and feedback are
removed and a wrong session length is fixed. If nothing usable is left, or the reply repeats the
previous question, the model is asked once more with a stricter instruction; after that a fixed
line for the move is said. Each model call of a `say`, with its guard result, is kept in
`last_calls` for the traces (R2).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

from strong_core.gateway import ModelGateway, Role
from strong_core.gateway.prices import cost_usd
from strong_core.gateway.registry import CapabilityTier
from strong_core.gateway.types import Completion, Message
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    BriefQuestion,
    InterviewerBrief,
    Phase,
    ProbeDecision,
    Speaker,
    Turn,
)
from strong_interview.controller import DEFAULT_PLAN, Move
from strong_interview.guard import GuardResult, fallback_line, guard_reply
from strong_interview.trace import ModelCall

log = logging.getLogger(__name__)

SMALL_WINDOW = 6  # turns shown to small-tier models
WINDOW = 16
SMALL_MAX_WORDS = 30
MAX_WORDS = 35  # about 14 seconds of speech; two short sentences
_LABEL = re.compile(r"^\s*(interviewer|[a-z]+)\s*:\s*", re.IGNORECASE)


@dataclass(frozen=True)
class SessionFacts:
    """What the interviewer may say about the company and the job when the candidate asks.

    Only these facts are used; for anything else the interviewer says it does not know.
    """

    company_name: str | None = None
    job_title: str | None = None
    team: str | None = None
    notes: tuple[str, ...] = ()

    def render(self) -> str:
        lines = []
        if self.company_name:
            lines.append(f"Company: {self.company_name}")
        if self.job_title:
            lines.append(f"Job: {self.job_title}")
        if self.team:
            lines.append(f"Team: {self.team}")
        lines += [f"- {note}" for note in self.notes]
        return "\n".join(lines) or "No facts are available."


def render_transcript(turns: Sequence[Turn], window: int) -> str:
    shown = list(turns)[-window:] if window else list(turns)
    if not shown:
        return "(nothing yet)"
    names = {Speaker.INTERVIEWER: "Interviewer", Speaker.CANDIDATE: "Candidate"}
    return "\n".join(f"{names[t.speaker]}: {t.text}" for t in shown)


def previous_interviewer_text(turns: Sequence[Turn]) -> str | None:
    """The interviewer's latest turn, for the repeat check."""
    for turn in reversed(turns):
        if turn.speaker == Speaker.INTERVIEWER:
            return turn.text
    return None


def clean_reply(text: str) -> str:
    """Spoken text only: no speaker label, no markdown emphasis."""
    text = _LABEL.sub("", text.strip(), count=1)
    return text.replace("**", "").replace("*", "").strip()


class Interviewer:
    def __init__(
        self,
        gateway: ModelGateway,
        brief: InterviewerBrief,
        *,
        name: str = "Alex",
        facts: SessionFacts | None = None,
    ) -> None:
        self.gateway = gateway
        self.brief = brief
        self.name = name
        self.facts = facts or SessionFacts(company_name=brief.company_name)
        self.small = gateway.capabilities(Role.INTERVIEWER).tier == CapabilityTier.SMALL
        self.window = SMALL_WINDOW if self.small else WINDOW
        self.prompt_refs: set[str] = set()
        self.model: str | None = None
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0  # interviewer calls with a known price (R2)
        self.last_call: ModelCall | None = None  # the latest say or decide call, for traces
        self.last_calls: list[ModelCall] = []  # every model call of the latest say, in order
        self.plan_minutes: dict[Phase, int] = (
            {p.phase: p.minutes for p in brief.time_plan}
            if brief.time_plan
            else DEFAULT_PLAN[brief.session.duration_min]
        )

    @property
    def duration_min(self) -> int:
        return self.brief.session.duration_min

    def plan_text(self) -> str:
        """The session plan for the agenda, in plain words, from the brief's time plan."""
        core = self.plan_minutes.get(Phase.CORE, 0)
        questions = self.plan_minutes.get(Phase.CANDIDATE_QUESTIONS, 0)
        if self.brief.session.is_mini:
            return (
                f"This is a {self.duration_min}-minute mini interview: about {core} minutes of "
                "questions, then a short close. There is no separate time for the candidate's "
                "questions."
            )
        if questions <= 0:
            return f"About {core} minutes of questions, then a short close."
        return (
            f"About {core} minutes of questions, then about {questions} minutes for the "
            "candidate's questions, then a short close."
        )

    # ------------------------------------------------------------------ prompts

    def _system(self) -> Message:
        brief = self.brief
        company = (
            f"The company is {brief.company_name}."
            if brief.company_name
            else "No company is named; use a general tech interview style."
        )
        return load_prompt(Role.INTERVIEWER, "turn").message(
            "system",
            interviewer_name=self.name,
            interview_type=brief.session.interview_type.value.replace("_", " "),
            level=brief.session.level.value.replace("_", " "),
            company_line=company,
            tone=brief.persona.tone,
            pushback_style=brief.persona.pushback_style,
            closing_style=brief.persona.closing_style,
            seniority_bar=brief.seniority_bar or "Use the usual bar for this level.",
            max_words=str(SMALL_MAX_WORDS if self.small else MAX_WORDS),
            facts=self.facts.render(),
        )

    def turn_messages(self, move: Move, turns: Sequence[Turn]) -> list[Message]:
        user = load_prompt(Role.INTERVIEWER, "turn_input").message(
            "user",
            transcript=render_transcript(turns, self.window),
            move=move.kind.value,
            question=move.question.text if move.question else "none",
            missing=", ".join(m.value.replace("_", " ") for m in move.missing) or "none",
            pushback="on" if move.pushback else "off",
            duration_min=str(self.duration_min),
            plan=self.plan_text(),
        )
        return [self._system(), user]

    def retry_messages(self, messages: list[Message]) -> list[Message]:
        """The same turn, with a stricter instruction after a reply the guard rejected."""
        retry = load_prompt(Role.INTERVIEWER, "turn_retry").message(
            "user", duration_min=str(self.duration_min)
        )
        return [*messages, retry]

    def _note(
        self,
        done: Completion[object],
        messages: list[Message],
        raw: str,
        started: float,
        guard: dict[str, Any] | None = None,
    ) -> None:
        self.prompt_refs.update(done.prompt_refs)
        self.model = done.model
        self.input_tokens += done.usage.input_tokens
        self.output_tokens += done.usage.output_tokens
        try:
            cost = cost_usd(done.profile, done.model, done.usage)
        except Exception:
            log.warning("could not price the interviewer call", exc_info=True)
            cost = None
        self.cost_usd += cost or 0.0
        self.last_call = ModelCall(
            messages=tuple(messages),
            raw_reply=raw,
            model=done.model,
            prompt_refs=done.prompt_refs,
            input_tokens=done.usage.input_tokens,
            output_tokens=done.usage.output_tokens,
            cost_usd=cost,
            latency_ms=_ms_since(started),
            guard=guard,
        )

    # ------------------------------------------------------------------ calls

    def _guard(self, text: str, move: Move, previous: str | None) -> GuardResult:
        return guard_reply(
            clean_reply(text),
            move.kind,
            duration_min=self.duration_min,
            plan_minutes=self.plan_minutes.values(),
            previous=previous,
        )

    async def _say_once(
        self, move: Move, messages: list[Message], previous: str | None, attempt: int
    ) -> GuardResult:
        started = time.perf_counter()
        done = await self.gateway.complete(Role.INTERVIEWER, messages)
        raw = str(done.output)
        result = self._guard(raw, move, previous)
        action = "none"
        if result.hits:
            action = "fixed" if result.usable else ("retry" if attempt == 1 else "fallback")
            log.warning(
                "interviewer guard: move %s, attempt %d, rules %s, action %s",
                move.kind.value,
                attempt,
                ",".join(result.rules),
                action,
            )
        guard = {"attempt": attempt, "action": action, **result.as_dict()}
        self._note(done, messages, raw, started, guard)
        if self.last_call is not None:
            self.last_calls.append(self.last_call)
        return result

    async def say(self, move: Move, turns: Sequence[Turn]) -> str:
        """What the interviewer says for the move, after the output guard.

        A gateway error on the first call is raised. A reply the guard rejects gets one more
        call with a stricter instruction; if that is rejected too, or fails, the fixed line for
        the move is said.
        """
        messages = self.turn_messages(move, turns)
        previous = previous_interviewer_text(turns)
        self.last_call = None
        self.last_calls = []
        result = await self._say_once(move, messages, previous, attempt=1)
        if result.usable:
            return result.text
        retry = self.retry_messages(messages)
        started = time.perf_counter()
        try:
            result = await self._say_once(move, retry, previous, attempt=2)
        except Exception as exc:
            log.warning("interviewer retry failed; saying the fixed line", exc_info=True)
            result = GuardResult("")
            self.last_call = ModelCall(
                messages=tuple(retry),
                raw_reply=None,
                model=self.gateway.config.alias_for(Role.INTERVIEWER),
                prompt_refs=tuple(m.prompt_ref for m in retry if m.prompt_ref),
                latency_ms=_ms_since(started),
                error=f"{type(exc).__name__}: {exc}"[:2000],
                guard={"attempt": 2, "action": "fallback", "rules": [], "hits": []},
            )
            self.last_calls.append(self.last_call)
        if result.usable:
            return result.text
        return fallback_line(
            move.kind,
            name=self.name,
            duration_min=self.duration_min,
            mini=self.brief.session.is_mini,
            question=move.question.text if move.question else None,
        )

    async def say_stream(self, move: Move, turns: Sequence[Turn]) -> AsyncIterator[str]:
        """The same prompt as `say`, streamed, so speech could start before the reply is done.

        Not guarded, and not used for spoken replies today. Anything spoken must use `say`.
        """
        messages = self.turn_messages(move, turns)
        self.prompt_refs.update(m.prompt_ref for m in messages if m.prompt_ref)
        async for chunk in self.gateway.stream(Role.INTERVIEWER, messages):
            yield chunk

    async def decide(
        self, question: BriefQuestion, answer: str, turns: Sequence[Turn]
    ) -> ProbeDecision:
        """Probe or move on after an answer in CORE (IV-3). Moves on if the model fails."""
        brief = self.brief
        messages = [
            load_prompt(Role.INTERVIEWER, "decide").message("system"),
            load_prompt(Role.INTERVIEWER, "decide_input").message(
                "user",
                interview_type=brief.session.interview_type.value.replace("_", " "),
                level=brief.session.level.value.replace("_", " "),
                question=question.text,
                probe_hints="; ".join(question.probe_hints) or "none",
                answer=answer,
                transcript=render_transcript(turns, self.window),
            ),
        ]
        started = time.perf_counter()
        self.last_call = None
        try:
            done = await self.gateway.complete(
                Role.INTERVIEWER, messages, output_type=ProbeDecision
            )
        except Exception as exc:
            log.warning("probe decision failed; moving on", exc_info=True)
            self.last_call = ModelCall(
                messages=tuple(messages),
                raw_reply=None,
                model=self.gateway.config.alias_for(Role.INTERVIEWER),
                prompt_refs=tuple(m.prompt_ref for m in messages if m.prompt_ref),
                latency_ms=_ms_since(started),
                error=f"{type(exc).__name__}: {exc}"[:2000],
            )
            return ProbeDecision(action="move_on")
        self._note(done, messages, done.output.model_dump_json(), started)
        return done.output


def _ms_since(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
