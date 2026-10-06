"""P5 fixture recorder: a real gateway call saved as a fixture and replayed by the fake (PL-1)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from strong_core.config import Settings, find_repo_root
from strong_core.gateway import GatewayError, Message, ModelGateway, Role, build_gateway
from strong_core.gateway.fake import DEFAULT_FIXTURES_DIR, messages_hash, read_recording
from strong_core.gateway.recorder import RecordingGateway, main
from strong_core.gateway.registry import load_models_config
from strong_core.schemas import GapAnalysis, Scorecard

REPO = find_repo_root()
SCORECARD = (DEFAULT_FIXTURES_DIR / "scorer" / "Scorecard.json").read_text(encoding="utf-8")
MESSAGES = [
    Message(role="system", content="Score this.", prompt_ref="scorer/rubric.v1"),
    Message(role="user", content="Interviewer: hi. Candidate: hello."),
]


def _model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    if info.output_tools:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, SCORECARD)])
    return ModelResponse(parts=[TextPart("A recorded reply. Two sentences.")])


async def _stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
    for part in ("A streamed ", "reply."):
        yield part


def _real() -> ModelGateway:
    config = load_models_config(REPO / "config", "local")
    model = FunctionModel(_model, stream_function=_stream)
    return ModelGateway(config, model_factory=lambda alias, cfg: model)


def _fake(fixtures: Path) -> ModelGateway:
    return build_gateway(Settings(model_profile="fake", fake_fixtures_dir=fixtures))


async def test_recorded_structured_call_replays_on_fake(tmp_path: Path) -> None:
    rec = RecordingGateway(_real(), fixtures_dir=tmp_path)
    live = await rec.complete(Role.SCORER, MESSAGES, output_type=Scorecard)

    path = tmp_path / "scorer" / f"{messages_hash(MESSAGES)}.json"
    assert rec.saved == [path]
    recording = read_recording(path)
    assert recording is not None
    assert recording.profile == "local"
    assert recording.model == "local-mid"
    assert recording.output_type == "Scorecard"
    assert recording.messages == MESSAGES
    assert recording.prompt_refs == ["scorer/rubric.v1"]

    replay = await _fake(tmp_path).complete(Role.SCORER, MESSAGES, output_type=Scorecard)
    assert replay.output == live.output
    assert replay.usage == live.usage


async def test_recorded_text_and_stream_replay(tmp_path: Path) -> None:
    rec = RecordingGateway(_real(), fixtures_dir=tmp_path)
    live = await rec.complete(Role.INTERVIEWER, MESSAGES)
    fake = _fake(tmp_path)
    assert (await fake.complete(Role.INTERVIEWER, MESSAGES)).output == live.output

    other = [Message(role="user", content="Stream this one.")]
    streamed = "".join([c async for c in rec.stream(Role.PLANNER, other)])
    assert (await fake.complete(Role.PLANNER, other)).output == streamed


async def test_recording_for_another_type_falls_back_to_default(tmp_path: Path) -> None:
    rec = RecordingGateway(_real(), fixtures_dir=tmp_path)
    await rec.complete(Role.SCORER, MESSAGES, output_type=Scorecard)
    (tmp_path / "scorer" / "GapAnalysis.json").write_text(
        (DEFAULT_FIXTURES_DIR / "planner" / "GapAnalysis.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    done = await _fake(tmp_path).complete(Role.SCORER, MESSAGES, output_type=GapAnalysis)
    assert isinstance(done.output, GapAnalysis)


def test_recording_needs_a_real_profile() -> None:
    with pytest.raises(GatewayError, match="real profile"):
        RecordingGateway(build_gateway(Settings(model_profile="fake")))


def test_cli_refuses_the_fake_profile(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    request.write_text(json.dumps([m.model_dump() for m in MESSAGES]), encoding="utf-8")
    with pytest.raises(GatewayError):
        main(["--role", "scorer", "--messages", str(request), "--output-type", "Scorecard"])
