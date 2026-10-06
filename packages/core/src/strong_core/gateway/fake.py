"""Deterministic fake backend for MODEL_PROFILE=fake. Returns recorded fixtures, no network.

Fixture lookup for complete() and stream(), first match wins:

    <fixtures>/<role>/<messages-hash>.json|.txt   exact recording for one conversation
    <fixtures>/<role>/<OutputType>.json            default for a structured output type
    <fixtures>/<role>/text.txt                     default text reply for the role

An exact `<messages-hash>.json` is either the bare output, or a Recording written by
strong_core.gateway.recorder against a real profile. A Recording keeps the request too, and
replays its recorded token usage. It is used only when its output type matches the call.

transcribe() looks for <fixtures>/stt/<audio-hash>.txt, then stt/text.txt.
The error message prints the hash, so recording a new fixture is copy and paste.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import wave
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from strong_core.gateway.types import Message, Role, TokenUsage

DEFAULT_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


RECORDING_FORMAT = 1


class FakeFixtureMissingError(LookupError):
    pass


class RecordedUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class Recording(BaseModel):
    """One real gateway call, request and response, saved as <role>/<messages-hash>.json."""

    model_config = ConfigDict(extra="forbid")

    recording: int = Field(default=RECORDING_FORMAT, description="Format version.")
    role: Role
    profile: str = Field(description="The MODEL_PROFILE it was recorded with, never fake.")
    model: str = Field(description="Gateway alias from config, never a vendor id.")
    output_type: str | None = Field(description="Contract class name, or None for text.")
    messages: list[Message]
    prompt_refs: list[str] = Field(default_factory=list)
    output: Any = Field(description="The validated output as JSON, or the text reply.")
    usage: RecordedUsage = Field(default_factory=RecordedUsage)
    recorded_at: str

    @property
    def token_usage(self) -> TokenUsage:
        return TokenUsage(self.usage.input_tokens, self.usage.output_tokens)


def read_recording(path: Path) -> Recording | None:
    """The Recording in `path`, or None when the file holds a bare output instead."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "recording" in data:
        return Recording.model_validate(data)
    return None


def messages_hash(messages: Sequence[Message]) -> str:
    payload = json.dumps([[m.role, m.content] for m in messages], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def audio_hash(audio: bytes) -> str:
    return hashlib.sha256(audio).hexdigest()[:16]


class FakeBackend:
    def __init__(self, fixtures_dir: Path | None = None) -> None:
        self.fixtures_dir = fixtures_dir or DEFAULT_FIXTURES_DIR

    def complete(
        self, role: Role, messages: Sequence[Message], output_type: type[BaseModel] | None
    ) -> tuple[object, TokenUsage]:
        key = messages_hash(messages)
        folder = self.fixtures_dir / role.value
        recorded = self._recording(folder / f"{key}.json", output_type)
        if recorded is not None:
            if output_type is None:
                return str(recorded.output), recorded.token_usage
            return output_type.model_validate(recorded.output), recorded.token_usage
        if output_type is None:
            path = self._first(folder / f"{key}.txt", folder / "text.txt")
            if path is None:
                raise self._missing(role, key, "text.txt")
            text = path.read_text(encoding="utf-8").strip()
            return text, _usage(messages, text)
        exact = folder / f"{key}.json"
        candidates = [folder / f"{output_type.__name__}.json"]
        if exact.exists() and read_recording(exact) is None:  # a bare output, not a Recording
            candidates.insert(0, exact)
        path = self._first(*candidates)
        if path is None:
            raise self._missing(role, key, f"{output_type.__name__}.json")
        raw = path.read_text(encoding="utf-8")
        return output_type.model_validate_json(raw), _usage(messages, raw)

    async def stream(self, role: Role, messages: Sequence[Message]) -> AsyncIterator[str]:
        text, _ = self.complete(role, messages, None)
        assert isinstance(text, str)
        parts = _SENTENCE.split(text)
        for i, part in enumerate(parts):
            yield part if i == len(parts) - 1 else part + " "

    def transcribe(self, audio: bytes) -> str:
        folder = self.fixtures_dir / Role.STT.value
        key = audio_hash(audio)
        path = self._first(folder / f"{key}.txt", folder / "text.txt")
        if path is None:
            raise self._missing(Role.STT, key, "text.txt")
        return path.read_text(encoding="utf-8").strip()

    def synthesize(self, text: str) -> bytes:
        """Silent 16 kHz mono WAV, 10 ms per character (max 30 s). Same text, same bytes."""
        frames = min(len(text), 3000) * 160
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * frames)
        return buf.getvalue()

    def synthesize_pcm(self, text: str, sample_rate: int) -> list[bytes]:
        """Silent raw PCM, 10 ms per character (max 30 s), in 100 ms chunks."""
        total = min(len(text), 3000) * sample_rate // 100
        step = sample_rate // 10
        return [b"\x00\x00" * min(step, total - i) for i in range(0, total, step)]

    @staticmethod
    def _recording(path: Path, output_type: type[BaseModel] | None) -> Recording | None:
        if not path.exists():
            return None
        recorded = read_recording(path)
        if recorded is None:
            return None
        wanted = None if output_type is None else output_type.__name__
        return recorded if recorded.output_type == wanted else None

    @staticmethod
    def _first(*paths: Path) -> Path | None:
        return next((p for p in paths if p.exists()), None)

    def _missing(self, role: Role, key: str, default_name: str) -> FakeFixtureMissingError:
        folder = self.fixtures_dir / role.value
        return FakeFixtureMissingError(
            f"No fake fixture for role={role.value}. Add {folder / default_name} "
            f"or an exact recording named {key}.json / {key}.txt in {folder}."
        )


def _usage(messages: Sequence[Message], output: str) -> TokenUsage:
    # Rough and deterministic: about 4 characters per token.
    return TokenUsage(
        input_tokens=sum(len(m.content) for m in messages) // 4, output_tokens=len(output) // 4
    )
