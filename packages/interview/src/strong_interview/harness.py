"""Adapter for the P5 eval harness (strong_evals.session.run_text_session).

The harness has its own simple controller and calls `speak(state)` and `follow_up(state)`. This
adapter answers with the P7 interviewer: the same prompts, the same probe-or-move-on decision
and the same probe limit per difficulty. It reads the harness state by attribute, so this
package does not import strong_evals.
"""

from __future__ import annotations

from typing import Any

from strong_core.gateway import ModelGateway
from strong_core.schemas import InterviewerBrief, Phase, Speaker
from strong_interview.controller import PROBE_LIMIT, Move, MoveKind
from strong_interview.interviewer import Interviewer

_OPENING = {
    Phase.INTRO: MoveKind.GREET,
    Phase.SMALL_TALK: MoveKind.SMALL_TALK,
    Phase.AGENDA: MoveKind.AGENDA,
    Phase.CORE: MoveKind.ASK,
    Phase.WRAP_UP: MoveKind.WRAP_UP,
}


class HarnessInterviewer:
    """Implements strong_evals.interfaces.Interviewer with the P7 interviewer."""

    def __init__(self, gateway: ModelGateway, name: str = "Alex") -> None:
        self.gateway = gateway
        self.name = name
        self._interviewer: Interviewer | None = None
        self.decisions = 0
        self.probes = 0

    def _for(self, brief: InterviewerBrief) -> Interviewer:
        if self._interviewer is None or self._interviewer.brief is not brief:
            self._interviewer = Interviewer(self.gateway, brief, name=self.name)
        return self._interviewer

    async def speak(self, state: Any) -> str:
        phase: Phase = state.phase
        if phase == Phase.CANDIDATE_QUESTIONS:
            last = state.turns[-1] if state.turns else None
            answering = last and last.speaker == Speaker.CANDIDATE and last.phase == phase
            kind = MoveKind.ANSWER_QUESTION if answering else MoveKind.INVITE_QUESTIONS
        else:
            kind = _OPENING[phase]
        question = state.question if phase == Phase.CORE else None
        return await self._for(state.brief).say(Move(kind, phase, question), state.turns)

    async def follow_up(self, state: Any) -> str | None:
        brief: InterviewerBrief = state.brief
        limit = min(brief.max_probes_per_question, PROBE_LIMIT[brief.session.difficulty])
        if state.question is None or state.probes_used >= limit or not state.turns:
            return None
        last = state.turns[-1]
        if last.speaker != Speaker.CANDIDATE:
            return None
        interviewer = self._for(brief)
        self.decisions += 1
        decision = await interviewer.decide(state.question, last.text, state.turns)
        if decision.action != "probe":
            return None
        self.probes += 1
        move = Move(
            MoveKind.PROBE,
            Phase.CORE,
            state.question,
            tuple(decision.missing),
            pushback=brief.pushback,
        )
        return await interviewer.say(move, state.turns)
