"""Interviewer turn logic: what to say for each move, and the probe-or-move-on decision.

All model calls go through the gateway with the interviewer role, and all text comes from
prompts/interviewer/. Small-tier models get the small prompt variants (PL-5) and a shorter
turn window. The decision after an answer is a ProbeDecision, a constrained choice; if the
model fails to return one, the interviewer moves on.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from strong_core.gateway import ModelGateway, Role
from strong_core.gateway.registry import CapabilityTier
from strong_core.gateway.types import Completion, Message
from strong_core.prompts import load_prompt
from strong_core.schemas import BriefQuestion, InterviewerBrief, ProbeDecision, Speaker, Turn
from strong_interview.controller import Move

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
        )
        return [self._system(), user]

    def _note(self, done: Completion[object]) -> None:
        self.prompt_refs.update(done.prompt_refs)
        self.model = done.model
        self.input_tokens += done.usage.input_tokens
        self.output_tokens += done.usage.output_tokens

    # ------------------------------------------------------------------ calls

    async def say(self, move: Move, turns: Sequence[Turn]) -> str:
        done = await self.gateway.complete(Role.INTERVIEWER, self.turn_messages(move, turns))
        self._note(done)
        return clean_reply(str(done.output)) or "Let's continue."

    async def say_stream(self, move: Move, turns: Sequence[Turn]) -> AsyncIterator[str]:
        """The same reply as `say`, streamed, so speech can start before the reply is done."""
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
        try:
            done = await self.gateway.complete(
                Role.INTERVIEWER, messages, output_type=ProbeDecision
            )
        except Exception:
            log.warning("probe decision failed; moving on", exc_info=True)
            return ProbeDecision(action="move_on")
        self._note(done)
        return done.output
