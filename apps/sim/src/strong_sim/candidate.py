"""The candidate: a model (role `candidate`) that plays a synthetic person from a resume fixture.

The persona prompt combines the resume, the posting, an answer quality (strong, average, weak) and
a behavior (long answers, off topic, prompt injection, ...). The reply is the words the candidate
says. "[silence]" is a reply with no words: text sends "...", voice stays quiet.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from strong_core.gateway import Message, ModelGateway, Role
from strong_core.prompts import load_prompt
from strong_sim.cost import CostMeter
from strong_sim.scenarios import FIXTURES_DIR, Scenario
from strong_sim.transcript import Line

log = logging.getLogger("strong_sim")

SILENCE = "[silence]"
RATE_LIMIT_WAIT_S = 20.0
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


def _rate_limited(exc: BaseException) -> bool:
    return getattr(exc, "status_code", None) == 429 or "RateLimitError" in str(exc)[:300]


@dataclass
class Pacer:
    """Spaces candidate calls (min_interval_s) and retries on HTTP 429.

    A provider's free tier allows only a few requests per minute (Gemini: 5 per model). One pacer
    is shared by all sessions of a run.
    """

    min_interval_s: float = 0.0
    retries: int = 6
    _last: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def wait_turn(self) -> None:
        async with self._lock:
            delay = self._last + self.min_interval_s - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = time.monotonic()


@dataclass
class Candidate:
    scenario: Scenario
    gateway: ModelGateway
    meter: CostMeter
    pacer: Pacer = field(default_factory=Pacer)

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
        for attempt in range(self.pacer.retries + 1):
            await self.pacer.wait_turn()
            try:
                done = await self.gateway.complete(Role.CANDIDATE, messages)
                break
            except Exception as exc:
                if not _rate_limited(exc) or attempt == self.pacer.retries:
                    raise
                log.warning("candidate model rate limited; waiting %.0f s", RATE_LIMIT_WAIT_S)
                await asyncio.sleep(RATE_LIMIT_WAIT_S)
        self.meter.add(done)
        return clean(str(done.output)) or SILENCE
