"""PL-1: every model call goes through the gateway by role; config picks the model."""

from __future__ import annotations

import io
import wave
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from strong_core.config import Settings, find_repo_root
from strong_core.gateway import (
    FakeFixtureMissingError,
    GatewayError,
    Message,
    ModelGateway,
    Role,
    build_gateway,
    load_models_config,
)
from strong_core.gateway.fake import DEFAULT_FIXTURES_DIR, messages_hash
from strong_core.gateway.registry import ModelsConfig
from strong_core.schemas import GapAnalysis, JobPosting, Scorecard

REPO = find_repo_root()
USER = [Message(role="user", content="Parse this posting.")]


@pytest.fixture
def fake() -> ModelGateway:
    return build_gateway(Settings(model_profile="fake"))


async def test_fake_complete_returns_validated_contract(fake: ModelGateway) -> None:
    done = await fake.complete(Role.EXTRACTOR, USER, output_type=JobPosting)
    assert isinstance(done.output, JobPosting)
    assert done.model == "fake-extractor"
    assert done.profile == "fake"


async def test_fake_is_deterministic(fake: ModelGateway) -> None:
    a = await fake.complete(Role.SCORER, USER, output_type=Scorecard)
    b = await fake.complete(Role.SCORER, USER, output_type=Scorecard)
    assert a == b


async def test_fake_exact_recording_wins(tmp_path: Path) -> None:
    folder = tmp_path / "interviewer"
    folder.mkdir()
    (folder / "text.txt").write_text("default", encoding="utf-8")
    (folder / f"{messages_hash(USER)}.txt").write_text("recorded", encoding="utf-8")
    gw = build_gateway(Settings(model_profile="fake", fake_fixtures_dir=tmp_path))
    assert (await gw.complete(Role.INTERVIEWER, USER)).output == "recorded"
    other = [Message(role="user", content="something else")]
    assert (await gw.complete(Role.INTERVIEWER, other)).output == "default"


async def test_fake_missing_fixture_names_the_file(tmp_path: Path) -> None:
    gw = build_gateway(Settings(model_profile="fake", fake_fixtures_dir=tmp_path))
    with pytest.raises(FakeFixtureMissingError, match=r"GapAnalysis\.json"):
        await gw.complete(Role.PLANNER, USER, output_type=GapAnalysis)


async def test_fake_stream_yields_sentences(fake: ModelGateway) -> None:
    chunks = [c async for c in fake.stream(Role.INTERVIEWER, USER)]
    assert len(chunks) > 1
    assert "".join(chunks) == (await fake.complete(Role.INTERVIEWER, USER)).output


async def test_fake_audio(fake: ModelGateway) -> None:
    assert "migration" in await fake.transcribe(b"\x00\x01")
    audio = await fake.synthesize("Hello there.")
    with wave.open(io.BytesIO(audio)) as w:
        assert w.getframerate() == 16000
        assert w.getnframes() > 0
    assert audio == await fake.synthesize("Hello there.")


async def test_prompt_refs_are_recorded(fake: ModelGateway) -> None:
    msgs = [
        Message(role="system", content="sys", prompt_ref="extractor/job_posting.v2"),
        Message(role="user", content="text"),
    ]
    done = await fake.complete(Role.EXTRACTOR, msgs, output_type=JobPosting)
    assert done.prompt_refs == ("extractor/job_posting.v2",)


async def test_rejects_wrong_role_and_bad_messages(fake: ModelGateway) -> None:
    with pytest.raises(GatewayError):
        await fake.complete(Role.TTS, USER)
    with pytest.raises(GatewayError):
        await fake.complete(Role.EXTRACTOR, [Message(role="system", content="only system")])


@pytest.mark.parametrize("profile", ["local", "hosted"])
def test_config_files_cover_every_role(profile: str) -> None:
    config = load_models_config(REPO / "config", profile)
    assert set(config.roles) == set(Role)
    assert config.capabilities(Role.PLANNER).context_window >= 4096


def test_config_rejects_missing_role() -> None:
    config = load_models_config(REPO / "config", "local").model_dump()
    del config["roles"]["scorer"]
    with pytest.raises(ValueError, match="scorer"):
        ModelsConfig.model_validate(config)


def test_config_rejects_wrong_model_kind() -> None:
    config = load_models_config(REPO / "config", "local").model_dump()
    config["roles"]["stt"] = "local-small"
    with pytest.raises(ValueError, match="stt"):
        ModelsConfig.model_validate(config)


# --- Real (non-fake) path, driven by Pydantic AI's FunctionModel instead of a network model ---


def _gateway(fn: FunctionModel) -> ModelGateway:
    config = load_models_config(REPO / "config", "local")
    return ModelGateway(config, model_factory=lambda alias, cfg: fn)


async def test_real_path_structured_output_with_one_retry() -> None:
    calls: list[list[ModelMessage]] = []
    valid = (DEFAULT_FIXTURES_DIR / "extractor" / "JobPosting.json").read_text(encoding="utf-8")

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(list(messages))
        tool = info.output_tools[0].name
        if len(calls) == 1:
            return ModelResponse(parts=[ToolCallPart(tool, {"title": "missing company"})])
        return ModelResponse(parts=[ToolCallPart(tool, valid)])

    msgs = [
        Message(role="system", content="You extract jobs."),
        Message(role="user", content="first"),
        Message(role="assistant", content="ok"),
        Message(role="user", content="Parse this posting."),
    ]
    done = await _gateway(FunctionModel(model)).complete(Role.EXTRACTOR, msgs, JobPosting)

    assert isinstance(done.output, JobPosting)
    assert done.model == "local-small"
    assert len(calls) == 2  # one automatic retry after a validation error
    first = calls[0]
    assert isinstance(first[0], ModelRequest)
    assert isinstance(first[0].parts[0], UserPromptPart)
    assert first[0].parts[0].content == "first"
    assert isinstance(first[1], ModelResponse)
    last_request = first[-1]
    assert isinstance(last_request, ModelRequest)
    assert last_request.instructions == "You extract jobs."


async def test_real_path_fails_loudly_after_retry() -> None:
    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"bad": 1})])

    with pytest.raises(Exception, match=r"(?i)retr"):
        await _gateway(FunctionModel(model)).complete(Role.EXTRACTOR, USER, JobPosting)


async def test_real_path_text_and_stream() -> None:
    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("Hello. How are you?")])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        for piece in ["Hello. ", "How are ", "you?"]:
            yield piece

    gw = _gateway(FunctionModel(model, stream_function=stream))
    assert (await gw.complete(Role.INTERVIEWER, USER)).output == "Hello. How are you?"
    chunks = [c async for c in gw.stream(Role.INTERVIEWER, USER)]
    assert "".join(chunks) == "Hello. How are you?"
