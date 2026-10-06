"""Record real gateway calls as fake-model fixtures (P5).

Wrap a gateway built for a real profile. Every chat call is passed through and saved as
<fixtures>/<role>/<messages-hash>.json (a Recording: request and response). Every transcription is
saved as <fixtures>/stt/<audio-hash>.txt. With MODEL_PROFILE=fake, FakeBackend replays them.

    gateway = RecordingGateway(get_gateway(), fixtures_dir=Path("my-fixtures"))
    await gateway.complete(Role.SCORER, messages, output_type=Scorecard)  # real call, saved

One call from the command line (MODEL_PROFILE must be local or hosted):

    python -m strong_core.gateway.recorder --role scorer --messages request.json \\
        --output-type Scorecard [--fixtures-dir DIR]

request.json is a JSON list of messages: [{"role": "system", "content": "..."}, ...].
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar, overload

from pydantic import BaseModel, TypeAdapter

from strong_core.gateway.client import GatewayError, ModelGateway, get_gateway
from strong_core.gateway.fake import (
    DEFAULT_FIXTURES_DIR,
    RecordedUsage,
    Recording,
    audio_hash,
    messages_hash,
)
from strong_core.gateway.types import Completion, Message, Role

OutputT = TypeVar("OutputT", bound=BaseModel)


def recording_path(fixtures_dir: Path, role: Role, messages: Sequence[Message]) -> Path:
    return fixtures_dir / role.value / f"{messages_hash(messages)}.json"


def save_recording(
    fixtures_dir: Path,
    messages: Sequence[Message],
    done: Completion[Any],
    output_type: type[BaseModel] | None,
) -> Path:
    output = (
        done.output.model_dump(mode="json") if isinstance(done.output, BaseModel) else done.output
    )
    recording = Recording(
        role=done.role,
        profile=done.profile,
        model=done.model,
        output_type=None if output_type is None else output_type.__name__,
        messages=list(messages),
        prompt_refs=list(done.prompt_refs),
        output=output,
        usage=RecordedUsage(
            input_tokens=done.usage.input_tokens, output_tokens=done.usage.output_tokens
        ),
        recorded_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    path = recording_path(fixtures_dir, done.role, messages)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(recording.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


class RecordingGateway(ModelGateway):
    """A gateway that passes calls to `inner` and saves each one as a fixture."""

    def __init__(self, inner: ModelGateway, fixtures_dir: Path | None = None) -> None:
        if inner.is_fake:
            raise GatewayError("recording needs a real profile (local or hosted), not fake")
        super().__init__(inner.config, base_url=inner.base_url)
        self.inner = inner
        self.fixtures_dir = fixtures_dir or DEFAULT_FIXTURES_DIR
        self.saved: list[Path] = []

    @overload
    async def complete(
        self, role: Role, messages: Sequence[Message], output_type: None = None
    ) -> Completion[str]: ...

    @overload
    async def complete(
        self, role: Role, messages: Sequence[Message], output_type: type[OutputT]
    ) -> Completion[OutputT]: ...

    async def complete(
        self,
        role: Role,
        messages: Sequence[Message],
        output_type: type[BaseModel] | None = None,
    ) -> Completion[Any]:
        done: Completion[Any] = await self.inner.complete(role, messages, output_type)
        self.saved.append(save_recording(self.fixtures_dir, messages, done, output_type))
        return done

    async def stream(self, role: Role, messages: Sequence[Message]) -> AsyncIterator[str]:
        chunks: list[str] = []
        async for chunk in self.inner.stream(role, messages):
            chunks.append(chunk)
            yield chunk
        refs = tuple(dict.fromkeys(m.prompt_ref for m in messages if m.prompt_ref))
        done = Completion("".join(chunks), role, self.config.alias_for(role), self.profile, refs)
        self.saved.append(save_recording(self.fixtures_dir, messages, done, None))

    async def transcribe(self, audio: bytes, *, filename: str = "audio.wav") -> str:
        text = await self.inner.transcribe(audio, filename=filename)
        path = self.fixtures_dir / Role.STT.value / f"{audio_hash(audio)}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        self.saved.append(path)
        return text

    async def synthesize(self, text: str) -> bytes:
        return await self.inner.synthesize(text)

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        async for chunk in self.inner.synthesize_stream(text):
            yield chunk


def output_type_by_name(name: str) -> type[BaseModel]:
    from strong_core.schemas import EXPORTED_SCHEMAS

    by_name = {m.__name__: m for m in EXPORTED_SCHEMAS.values()}
    if name not in by_name:
        raise SystemExit(f"Unknown output type {name!r}. Known: {', '.join(sorted(by_name))}")
    return by_name[name]


async def _record_one(args: argparse.Namespace, messages: list[Message]) -> Path:
    gateway = RecordingGateway(
        get_gateway(), Path(args.fixtures_dir) if args.fixtures_dir else None
    )
    output_type = output_type_by_name(args.output_type) if args.output_type else None
    await gateway.complete(Role(args.role), messages, output_type)
    return gateway.saved[-1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record one real gateway call as a fixture.")
    parser.add_argument(
        "--role", required=True, choices=["extractor", "planner", "interviewer", "scorer"]
    )
    parser.add_argument("--messages", required=True, help="JSON file with a list of messages")
    parser.add_argument("--output-type", help="contract class name, for example Scorecard")
    parser.add_argument("--fixtures-dir", help="default: the fake model's fixtures folder")
    args = parser.parse_args(argv)
    raw = json.loads(Path(args.messages).read_text(encoding="utf-8"))
    messages = TypeAdapter(list[Message]).validate_python(raw)
    print(asyncio.run(_record_one(args, messages)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
