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

IV-12: `check_answer` asks whether a candidate turn belongs in the interview. It returns its
ModelCall instead of setting `last_call`, because it runs at the same time as `decide`.

Custom sessions (CU-4, CU-12, D-7, D-9): the prompts name the current question's category as
the interview type, and the agenda names the categories. A question the candidate wrote goes
into the prompts wrapped as quoted data (prompts/interviewer/question_candidate). It gets the
same follow-up rules as the planner's. A verbatim question is enforced in code: the model writes
only a short lead-in, and the spoken line is that lead-in plus the question text, unchanged. The
spoken line still passes the output guard. If the guard rejects the question text itself, the
question is asked in the interviewer's own words instead, through the normal path. The trace
marks the rejected line `verbatim: "rejected"` and the adapted calls `verbatim: "adapted"` (CU-5
risk).

Recruiter screen (RS-2): the system prompt is prompts/interviewer/turn_recruiter_screen, chosen
by the session's type (TURN_BY_TYPE), never by model.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, replace
from typing import Any

from strong_core.gateway import ModelGateway, Role
from strong_core.gateway.prices import cost_usd
from strong_core.gateway.registry import CapabilityTier
from strong_core.gateway.types import Completion, Message
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    AnswerCheck,
    AnswerConduct,
    BriefQuestion,
    InterviewerBrief,
    InterviewType,
    Phase,
    ProbeDecision,
    QuestionSource,
    Speaker,
    Turn,
)
from strong_interview.controller import DEFAULT_PLAN, Move, MoveKind
from strong_interview.guard import GuardResult, fallback_line, guard_reply
from strong_interview.trace import ModelCall

log = logging.getLogger(__name__)

SMALL_WINDOW = 6  # turns shown to small-tier models
WINDOW = 16
SMALL_MAX_WORDS = 30
MAX_WORDS = 35  # about 14 seconds of speech; two short sentences
_LABEL = re.compile(r"^\s*(interviewer|[a-z]+)\s*:\s*", re.IGNORECASE)
LEAD_IN_MAX_WORDS = 12  # D-7: the lead-in said before a verbatim question
VERBATIM_MOVES = (MoveKind.ASK, MoveKind.REDO)
_FIRST_SENTENCE = re.compile(r"^.*?[.!](?=\s|$)")
TURN_BY_TYPE = {InterviewType.RECRUITER_SCREEN: "turn_recruiter_screen"}
"""RS-2: a type with its own turn prompt. The others use prompts/interviewer/turn."""


def lead_in(text: str) -> str:
    """D-7: the short lead-in before a verbatim question, from the model's reply.

    Its first sentence, when it is short and asks nothing; else nothing, and the question is
    said on its own.
    """
    match = _FIRST_SENTENCE.match(text.strip())
    first = match.group(0).strip() if match else text.strip()
    if not first or "?" in first or len(first.split()) > LEAD_IN_MAX_WORDS:
        return ""
    return first


def quote_untrusted(text: str) -> str:
    """Text the candidate wrote, as one JSON-quoted line for a prompt (CU-5 risk).

    JSON quoting escapes quote marks, so the text cannot end the string early, and angle
    brackets are removed, so it cannot open or close a tag-delimited block.
    """
    flat = " ".join(text.replace("<", " ").replace(">", " ").split())
    return json.dumps(flat, ensure_ascii=False)


def say_names(names: Sequence[str]) -> str:
    """'behavioral', 'behavioral and technical', 'behavioral, technical and case'."""
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


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
            plan = f"About {core} minutes of questions, then a short close."
        else:
            plan = (
                f"About {core} minutes of questions, then about {questions} minutes for the "
                "candidate's questions, then a short close."
            )
        categories = self.categories()
        if len(categories) > 1:  # IV-7 for Custom: name the categories, in order
            plan += f" The questions cover {say_names(categories)}, in that order."
        return plan

    # ------------------------------------------------------------------ prompts

    def categories(self) -> list[str]:
        """A Custom session's categories in the candidate's order, as words. Empty otherwise."""
        custom = self.brief.session.custom
        if custom is None:
            return []
        return [c.category.value.replace("_", " ") for c in custom.categories]

    def interview_type(self, question: BriefQuestion | None = None) -> str:
        """The interview type for the prompts. In a Custom session, the question's category
        ("behavioral"), or all the categories when there is no question (CU-12)."""
        if question is not None and question.category is not None:
            return question.category.value.replace("_", " ")
        categories = self.categories()
        if categories:
            return say_names(categories)
        return self.brief.session.interview_type.value.replace("_", " ")

    def question_text(self, question: BriefQuestion) -> str:
        """The question for the prompts. The candidate's own text is JSON-quoted data with a
        note, so it is never read as an instruction (CU-5 risk)."""
        if question.source == QuestionSource.CANDIDATE:
            prompt = load_prompt(Role.INTERVIEWER, "question_candidate")
            return prompt.render(text=quote_untrusted(question.text)).strip()
        return question.text

    def _system(self, question: BriefQuestion | None = None) -> Message:
        brief = self.brief
        company = (
            f"The company is {brief.company_name}."
            if brief.company_name
            else "No company is named; use a general tech interview style."
        )
        name = TURN_BY_TYPE.get(brief.session.interview_type, "turn")
        return load_prompt(Role.INTERVIEWER, name).message(
            "system",
            interviewer_name=self.name,
            interview_type=self.interview_type(question),
            level=brief.session.level.value.replace("_", " "),
            company_line=company,
            tone=brief.persona.tone,
            pushback_style=brief.persona.pushback_style,
            closing_style=brief.persona.closing_style,
            seniority_bar=brief.seniority_bar or "Use the usual bar for this level.",
            max_words=str(SMALL_MAX_WORDS if self.small else MAX_WORDS),
            facts=self.facts.render(),
        )

    def _move_note(self, move: Move, adapted: bool = False) -> str:
        """An extra instruction for a closing move (from prompts/interviewer/note_*).

        `adapted`: a verbatim question asked in the interviewer's own words, so no verbatim note.
        """
        if move.closing:
            return load_prompt(Role.INTERVIEWER, "note_last_question").render().strip()
        if move.open_question:
            return load_prompt(Role.INTERVIEWER, "note_open_question").render().strip()
        if self.verbatim(move) and not adapted:
            return load_prompt(Role.INTERVIEWER, "note_verbatim").render().strip()
        return "none"

    @staticmethod
    def verbatim(move: Move) -> bool:
        """D-7: the move reads the question word for word."""
        return move.kind in VERBATIM_MOVES and move.question is not None and move.question.verbatim

    def turn_messages(
        self, move: Move, turns: Sequence[Turn], adapted: bool = False
    ) -> list[Message]:
        user = load_prompt(Role.INTERVIEWER, "turn_input").message(
            "user",
            transcript=render_transcript(turns, self.window),
            move=move.kind.value,
            question=self.question_text(move.question) if move.question else "none",
            missing=", ".join(m.value.replace("_", " ") for m in move.missing) or "none",
            pushback="on" if move.pushback else "off",
            duration_min=str(self.duration_min),
            plan=self.plan_text(),
            note=self._move_note(move, adapted),
        )
        return [self._system(move.question), user]

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
        self,
        move: Move,
        messages: list[Message],
        previous: str | None,
        attempt: int,
        flags: dict[str, Any] | None = None,
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
        guard = {"attempt": attempt, "action": action, **result.as_dict(), **(flags or {})}
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
        if self.verbatim(move):
            spoken = await self._say_verbatim(move, messages, previous)
            if spoken is not None:
                return spoken
            adapted = self.turn_messages(move, turns, adapted=True)
            return await self._say_guarded(move, adapted, previous, {"verbatim": "adapted"})
        return await self._say_guarded(move, messages, previous)

    async def _say_guarded(
        self,
        move: Move,
        messages: list[Message],
        previous: str | None,
        flags: dict[str, Any] | None = None,
    ) -> str:
        """The model's reply after the guard, one stricter retry, then the fixed line.

        `flags` go into each call's guard record. With flags set (a verbatim question the guard
        rejected), the fixed line never repeats the question text.
        """
        result = await self._say_once(move, messages, previous, attempt=1, flags=flags)
        if result.usable:
            return result.text
        retry = self.retry_messages(messages)
        started = time.perf_counter()
        try:
            result = await self._say_once(move, retry, previous, attempt=2, flags=flags)
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
                guard={
                    "attempt": 2,
                    "action": "fallback",
                    "rules": [],
                    "hits": [],
                    **(flags or {}),
                },
            )
            self.last_calls.append(self.last_call)
        if result.usable:
            return result.text
        return fallback_line(
            move.kind,
            name=self.name,
            duration_min=self.duration_min,
            mini=self.brief.session.is_mini,
            question=move.question.text if move.question and not flags else None,
            closing=move.closing,
            open_question=move.open_question,
        )

    async def _say_verbatim(
        self, move: Move, messages: list[Message], previous: str | None
    ) -> str | None:
        """D-7: the model's short lead-in, then the question text exactly as written.

        The model never says the question itself, so it cannot reword it. A lead-in the guard
        rejects, one that is long or asks something, or a failed call leaves only the question.

        The whole spoken line then passes the output guard too, unchanged or not at all: the
        guard may not edit the candidate's words. If the line with the lead-in breaks a rule,
        the question alone is checked. If the question text itself breaks a rule, this returns
        None and the caller asks it in the interviewer's own words (CU-5 risk); the trace
        record of the lead-in call carries the flag and the guard's hits.
        """
        assert move.question is not None
        question = move.question.text
        lead = ""
        try:
            result = await self._say_once(move, messages, previous, attempt=1)
            if result.usable:
                lead = lead_in(result.text)
        except Exception:
            log.warning("verbatim lead-in failed; saying the question alone", exc_info=True)
        spoken = f"{lead} {question}".strip()
        check = self._guard(spoken, move, previous)
        if check.hits and lead:
            spoken = question
            check = self._guard(spoken, move, previous)
        if not check.hits:
            return spoken
        log.warning(
            "interviewer guard rejected a verbatim question: rules %s; asking it adapted",
            ",".join(check.rules),
        )
        flag = {"verbatim": "rejected", "verbatim_guard": check.as_dict()}
        if self.last_calls:
            # The lead-in call's record carries the flag.
            last = self.last_calls[-1]
            self.last_calls[-1] = replace(last, guard={**(last.guard or {}), **flag})
        else:
            # The lead-in call failed and left no record: keep one for the trace.
            self.last_calls.append(
                ModelCall(
                    messages=tuple(messages),
                    raw_reply=None,
                    model=None,
                    prompt_refs=tuple(m.prompt_ref for m in messages if m.prompt_ref),
                    guard={"attempt": 1, "action": "adapted", "rules": [], "hits": [], **flag},
                )
            )
        return None

    async def say_stream(self, move: Move, turns: Sequence[Turn]) -> AsyncIterator[str]:
        """The same prompt as `say`, streamed, so speech could start before the reply is done.

        Not guarded, and not used for spoken replies today. Anything spoken must use `say`.
        """
        messages = self.turn_messages(move, turns)
        self.prompt_refs.update(m.prompt_ref for m in messages if m.prompt_ref)
        async for chunk in self.gateway.stream(Role.INTERVIEWER, messages):
            yield chunk

    async def check_answer(
        self,
        answer: str,
        turns: Sequence[Turn],
        phase: Phase,
        question: BriefQuestion | None = None,
    ) -> tuple[AnswerCheck, ModelCall]:
        """IV-12: is the candidate's turn outside the interview or inappropriate? Ok on failure.

        `question` is the open CORE question, which names the category of a Custom session.
        """
        messages = [
            load_prompt(Role.INTERVIEWER, "check_answer").message("system"),
            load_prompt(Role.INTERVIEWER, "check_answer_input").message(
                "user",
                interview_type=self.interview_type(question),
                phase=phase.value.replace("_", " "),
                asked=previous_interviewer_text(turns) or "(nothing yet)",
                answer=answer,
            ),
        ]
        started = time.perf_counter()
        try:
            done = await self.gateway.complete(Role.INTERVIEWER, messages, output_type=AnswerCheck)
        except Exception as exc:
            log.warning("answer check failed; the turn counts as ok", exc_info=True)
            return AnswerCheck(conduct=AnswerConduct.OK), ModelCall(
                messages=tuple(messages),
                raw_reply=None,
                model=self.gateway.config.alias_for(Role.INTERVIEWER),
                prompt_refs=tuple(m.prompt_ref for m in messages if m.prompt_ref),
                latency_ms=_ms_since(started),
                error=f"{type(exc).__name__}: {exc}"[:2000],
            )
        self.prompt_refs.update(done.prompt_refs)
        self.input_tokens += done.usage.input_tokens
        self.output_tokens += done.usage.output_tokens
        try:
            cost = cost_usd(done.profile, done.model, done.usage)
        except Exception:
            log.warning("could not price the answer check", exc_info=True)
            cost = None
        self.cost_usd += cost or 0.0
        call = ModelCall(
            messages=tuple(messages),
            raw_reply=done.output.model_dump_json(),
            model=done.model,
            prompt_refs=done.prompt_refs,
            input_tokens=done.usage.input_tokens,
            output_tokens=done.usage.output_tokens,
            cost_usd=cost,
            latency_ms=_ms_since(started),
        )
        return done.output, call

    async def decide(
        self, question: BriefQuestion, answer: str, turns: Sequence[Turn]
    ) -> ProbeDecision:
        """Probe or move on after an answer in CORE (IV-3). Moves on if the model fails."""
        brief = self.brief
        messages = [
            load_prompt(Role.INTERVIEWER, "decide").message("system"),
            load_prompt(Role.INTERVIEWER, "decide_input").message(
                "user",
                interview_type=self.interview_type(question),
                level=brief.session.level.value.replace("_", " "),
                question=self.question_text(question),
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
