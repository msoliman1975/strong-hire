"""Deterministic fake backend for MODEL_PROFILE=fake. Returns recorded fixtures, no network.

Fixture lookup for complete() and stream(), first match wins:

    <fixtures>/<role>/<messages-hash>.json|.txt   exact recording for one conversation
    <fixtures>/<role>/<OutputType>.json            default for a structured output type
    <fixtures>/<role>/text.txt                     default text reply for the role

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

from pydantic import BaseModel

from strong_core.gateway.types import Message, Role, TokenUsage

DEFAULT_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


class FakeFixtureMissingError(LookupError):
    pass


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
        if output_type is None:
            path = self._first(folder / f"{key}.txt", folder / "text.txt")
            if path is None:
                raise self._missing(role, key, "text.txt")
            text = path.read_text(encoding="utf-8").strip()
            return text, _usage(messages, text)
        path = self._first(folder / f"{key}.json", folder / f"{output_type.__name__}.json")
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
