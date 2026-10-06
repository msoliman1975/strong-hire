"""Stub planner, interviewer and scorer behind the harness interfaces.

They exist so the harness runs end to end before P6 to P8 land. They are deliberately simple:
- StubPlanner builds a brief from evals/config/question_bank.yaml, with no model call.
- StubInterviewer asks the brief questions in priority order and probes vague answers with a rule
  in code (spec, Follow-up rules). The interviewer role phrases every line.
- GatewayScorer sends the transcript to the scorer role and returns its Scorecard as is.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import yaml

from strong_core.gateway import Message, ModelGateway, Role
from strong_core.prompts import load_prompt
from strong_core.schemas import (
    COMPETENCIES_BY_TYPE,
    BriefQuestion,
    Difficulty,
    InterviewerBrief,
    PersonaBrief,
    Phase,
    Scorecard,
    SessionConfig,
    Speaker,
    Turn,
)
from strong_evals import EVALS_DIR
from strong_evals.candidate import PROMPT_ROLE, Persona
from strong_evals.interfaces import InterviewState
from strong_evals.metrics import is_vague, missing_elements
from strong_evals.transcripts import asked_question_refs

QUESTION_BANK = EVALS_DIR / "config" / "question_bank.yaml"
PROBES_BY_DIFFICULTY = {Difficulty.FRIENDLY: 2, Difficulty.REALISTIC: 3, Difficulty.TOUGH: 3}
CURVEBALL = "Ask the candidate to defend the opposite of their last decision."


def render_transcript(turns: Sequence[Turn]) -> str:
    lines = []
    for t in turns:
        who = "Interviewer" if t.speaker == Speaker.INTERVIEWER else "Candidate"
        ref = f" [{t.question_ref}]" if t.question_ref else ""
        lines.append(f"{who}{ref}: {t.text}")
    return "\n".join(lines) or "(nothing yet)"


class StubPlanner:
    def __init__(self, bank_file: Path = QUESTION_BANK) -> None:
        self.bank = yaml.safe_load(bank_file.read_text(encoding="utf-8"))

    async def brief(self, config: SessionConfig, persona: Persona) -> InterviewerBrief:
        rows = self.bank[config.interview_type.value]
        questions = [BriefQuestion(priority=i, **row) for i, row in enumerate(rows, start=1)]
        tough = config.difficulty == Difficulty.TOUGH
        return InterviewerBrief(
            session=config,
            company_name=None,
            generic_mode=True,
            target_competencies=list(COMPETENCIES_BY_TYPE[config.interview_type])[:6],
            questions=questions,
            probe_areas=[],
            persona=PersonaBrief(
                tone="direct and challenging" if tough else "professional and warm",
                pushback_style="asks why not the simpler option" if tough else "clarifying",
                closing_style="thanks the candidate and explains next steps",
            ),
            max_probes_per_question=PROBES_BY_DIFFICULTY[config.difficulty],
            curveball=CURVEBALL if tough else None,
        )


class StubInterviewer:
    def __init__(self, gateway: ModelGateway, name: str = "Jordan") -> None:
        self.gateway = gateway
        self.name = name

    def _move(self, state: InterviewState) -> str:
        if state.phase == Phase.CORE:
            return "ask_question"
        if state.phase == Phase.CANDIDATE_QUESTIONS:
            last = state.turns[-1] if state.turns else None
            answering = last and last.speaker == Speaker.CANDIDATE and last.phase == state.phase
            return "answer_question" if answering else "invite_questions"
        return {
            Phase.INTRO: "intro",
            Phase.SMALL_TALK: "small_talk",
            Phase.AGENDA: "agenda",
            Phase.WRAP_UP: "wrap_up",
        }[state.phase]

    async def _say(self, state: InterviewState, move: str) -> str:
        brief = state.brief
        system = load_prompt(PROMPT_ROLE, "stub_interviewer").message(
            "system",
            interviewer_name=self.name,
            interview_type=brief.session.interview_type.value,
            level=brief.session.level.value,
            tone=brief.persona.tone,
            pushback_style=brief.persona.pushback_style,
        )
        user = load_prompt(PROMPT_ROLE, "stub_interviewer_turn").message(
            "user",
            transcript=render_transcript(state.turns),
            move=move,
            question=state.question.text if state.question else "none",
        )
        done = await self.gateway.complete(Role.INTERVIEWER, [system, user])
        return done.output.strip()

    async def speak(self, state: InterviewState) -> str:
        return await self._say(state, self._move(state))

    async def follow_up(self, state: InterviewState) -> str | None:
        if state.question is None or state.probes_used >= state.brief.max_probes_per_question:
            return None
        last = state.turns[-1]
        if last.speaker != Speaker.CANDIDATE or not is_vague(last.text):
            return None
        return await self._say(state, f"probe_{missing_elements(last.text)[0]}")


class GatewayScorer:
    def __init__(self, gateway: ModelGateway) -> None:
        self.gateway = gateway

    async def score(self, brief: InterviewerBrief, turns: Sequence[Turn]) -> Scorecard:
        system_prompt = load_prompt(PROMPT_ROLE, "stub_scorer")
        asked = [
            q for ref in asked_question_refs(list(turns)) for q in brief.questions if q.id == ref
        ]
        user = load_prompt(PROMPT_ROLE, "stub_scorer_input").message(
            "user",
            interview_type=brief.session.interview_type.value,
            level=brief.session.level.value,
            competencies=", ".join(c.value for c in brief.target_competencies),
            questions="\n".join(
                f"{q.id}: {q.text} [{', '.join(c.value for c in q.competencies)}]" for q in asked
            ),
            transcript=render_transcript(turns),
        )
        messages: list[Message] = [system_prompt.message("system"), user]
        done = await self.gateway.complete(Role.SCORER, messages, output_type=Scorecard)
        return done.output.model_copy(
            update={"scorer_model": done.model, "rubric_version": system_prompt.ref}
        )
