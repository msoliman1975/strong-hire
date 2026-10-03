from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Role(StrEnum):
    """What a model is used for. Code asks for a role; config decides the model (PL-1)."""

    EXTRACTOR = "extractor"
    PLANNER = "planner"
    INTERVIEWER = "interviewer"
    SCORER = "scorer"
    STT = "stt"
    TTS = "tts"


CHAT_ROLES = frozenset({Role.EXTRACTOR, Role.PLANNER, Role.INTERVIEWER, Role.SCORER})


class Message(BaseModel):
    """A chat message. Set prompt_ref when the content came from the prompt loader."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str
    prompt_ref: str | None = None


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class Completion[T]:
    """Result of ModelGateway.complete.

    `model` is the gateway alias from config (safe to store as GapAnalysis.model_version or
    Scorecard.scorer_model). `prompt_refs` lists the prompt versions found in the messages.
    """

    output: T
    role: Role
    model: str
    profile: str
    prompt_refs: tuple[str, ...] = ()
    usage: TokenUsage = field(default_factory=TokenUsage)
