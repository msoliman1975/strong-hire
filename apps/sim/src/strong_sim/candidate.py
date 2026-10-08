"""The candidate: a model (role `candidate`) that plays a synthetic person from a resume fixture.

The persona prompt combines the resume, the posting, an answer quality (strong, average, weak) and
a behavior (long answers, off topic, prompt injection, ...). The reply is the words the candidate
says. "[silence]" is a reply with no words: text sends "...", voice stays quiet.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from strong_core.gateway import Message, ModelGateway, Role
from strong_core.prompts import load_prompt
from strong_sim.cost import CostMeter
from strong_sim.scenarios import FIXTURES_DIR, Scenario
from strong_sim.transcript import Line

SILENCE = "[silence]"
_STAGE = re.compile(r"^\s*[\[(*][^\])*]{0,40}[\])*]\s*")  # a leading "(smiles)" or "*pauses*"


def fixture_text(kind: str, name: str) -> str:
    return (FIXTURES_DIR / kind / f"{name}.txt").read_text(encoding="utf-8").strip()


def clean(text: str) -> str:
    """Keep only the spoken words: drop quotes, a speaker label and leading stage directions."""
    text = text.strip().strip('"').strip()
    text = re.sub(r"^((?i:candidate|me)|[A-Z][a-z]+ [A-Z][a-z]+)\s*:\s*", "", text)
    if text.strip().lower() == SILENCE:
        return SILENCE
    while _STAGE.match(text) and not text.lower().startswith(SILENCE):
        text = _STAGE.sub("", text, count=1)
    return " ".join(text.split())


@dataclass
class Candidate:
    scenario: Scenario
    gateway: ModelGateway
    meter: CostMeter

    def __post_init__(self) -> None:
        s = self.scenario
        self.system = load_prompt("candidate", "persona").message(
            "system",
            name=s.candidate_name,
            level=s.fixture.level.value,
            interview_type=s.interview_type.value.replace("_", " "),
            posting=fixture_text("postings", s.fixture.posting),
            resume=fixture_text("resumes", s.resume),
            quality_guide=load_prompt("candidate", f"quality_{s.quality.value}").render(),
            behavior_guide=load_prompt("candidate", f"behavior_{s.behavior.value}").render(),
        )

    @property
    def prompt_refs(self) -> list[str]:
        return [
            "candidate/persona",
            f"candidate/quality_{self.scenario.quality.value}",
            f"candidate/behavior_{self.scenario.behavior.value}",
        ]

    async def reply(self, lines: Sequence[Line]) -> str:
        """The candidate's next words. The last line must be the interviewer's."""
        messages = [self.system]
        for line in lines:
            role = "user" if line.speaker == "interviewer" else "assistant"
            text = line.text or SILENCE
            if messages[-1].role == role:  # merge two turns in a row from one side
                last = messages.pop()
                messages.append(Message(role=role, content=f"{last.content}\n{text}"))
            else:
                messages.append(Message(role=role, content=text))
        if messages[-1].role != "user":
            messages.append(Message(role="user", content="(The interviewer waits for you.)"))
        done = await self.gateway.complete(Role.CANDIDATE, messages)
        self.meter.add(done)
        return clean(str(done.output)) or SILENCE
