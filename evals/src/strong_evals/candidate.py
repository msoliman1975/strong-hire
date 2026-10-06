"""Simulated candidate: an LLM (planner role) that plays a persona built from a Resume fixture.

It lets text-only interviews run without voice (spec, Build plan step 5). The quality level
(strong, average, weak) picks a prompt that tells the model how good its answers should be.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pydantic import Field

from strong_core.gateway import Message, ModelGateway, Role
from strong_core.prompts import load_prompt
from strong_core.schemas import Contract, InterviewType, Level, Resume, Speaker, Turn
from strong_evals import EVALS_DIR
from strong_evals.transcripts import Quality

RESUMES_DIR = EVALS_DIR / "fixtures" / "inputs" / "resumes"
PROMPT_ROLE = "evals"


class Persona(Contract):
    """Who the simulated candidate is. Synthetic people only."""

    name: str = Field(min_length=1)
    quality: Quality
    resume_id: str = Field(min_length=1, description="File name in evals/fixtures/inputs/resumes.")
    resume: Resume

    @classmethod
    def from_resume_fixture(
        cls, resume_id: str, quality: Quality, name: str, folder: Path = RESUMES_DIR
    ) -> Persona:
        resume = Resume.model_validate_json(
            (folder / f"{resume_id}.json").read_text(encoding="utf-8")
        )
        return cls(name=name, quality=quality, resume_id=resume_id, resume=resume)


def resume_text(resume: Resume) -> str:
    lines = [resume.summary or ""]
    for r in resume.roles:
        lines.append(f"{r.title}, {r.company} ({r.start or '?'} to {r.end or 'now'})")
        lines += [f"  - {a}" for a in r.achievements]
    if resume.skills:
        lines.append("Skills: " + ", ".join(resume.skills))
    for e in resume.education:
        lines.append(f"Education: {e.degree or ''} {e.field_of_study or ''}, {e.institution}")
    return "\n".join(line for line in lines if line.strip())


class SimulatedCandidate:
    def __init__(
        self,
        persona: Persona,
        gateway: ModelGateway,
        *,
        level: Level,
        interview_type: InterviewType,
    ) -> None:
        self.persona = persona
        self.gateway = gateway
        guide = load_prompt(PROMPT_ROLE, f"candidate_{persona.quality.value}")
        self.system = load_prompt(PROMPT_ROLE, "sim_candidate").message(
            "system",
            name=persona.name,
            level=level.value,
            interview_type=interview_type.value,
            resume=resume_text(persona.resume),
            quality_guide=guide.render(),
        )

    async def reply(self, turns: Sequence[Turn]) -> str:
        """The candidate's next turn. The last turn must be the interviewer's."""
        messages = [self.system] + [
            Message(
                role="user" if t.speaker == Speaker.INTERVIEWER else "assistant", content=t.text
            )
            for t in turns
        ]
        done = await self.gateway.complete(Role.PLANNER, messages)
        return done.output.strip()
