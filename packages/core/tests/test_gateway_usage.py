"""OB-2: with a usage context set, every gateway call reports role, units and cost."""

from __future__ import annotations

import io
import uuid
import wave
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from strong_core.config import Settings, find_repo_root, get_settings
from strong_core.db.models import Base, UsageEvent
from strong_core.gateway import (
    Message,
    ModelGateway,
    Role,
    UsageRecord,
    build_gateway,
    current_usage_context,
    get_usage_sink,
    load_models_config,
    make_db_usage_sink,
    set_usage_sink,
    usage_context,
)
from strong_core.gateway.usage import db_usage_sink
from strong_core.schemas import JobPosting
from strong_core.schemas.enums import UsageComponent

REPO = find_repo_root()
USER = [Message(role="user", content="Parse this posting.")]
ORG, SESSION = uuid.uuid4(), uuid.uuid4()


@pytest.fixture
def records() -> Iterator[list[UsageRecord]]:
    got: list[UsageRecord] = []

    async def sink(record: UsageRecord) -> None:
        got.append(record)

    previous = set_usage_sink(sink)
    yield got
    set_usage_sink(previous)


@pytest.fixture
def fake() -> ModelGateway:
    return build_gateway(Settings(model_profile="fake"))


def _wav(seconds: float, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


def test_default_sink_writes_to_the_database() -> None:
    assert get_usage_sink() is db_usage_sink


async def test_no_context_reports_nothing(fake: ModelGateway, records: list[UsageRecord]) -> None:
    """Callers that set no context behave exactly as before."""
    await fake.complete(Role.EXTRACTOR, USER, output_type=JobPosting)
    await fake.synthesize("Hello there.")
    assert records == []


async def test_context_is_scoped_to_the_block() -> None:
    assert current_usage_context() is None
    with usage_context(ORG, session_id=SESSION) as ctx:
        assert current_usage_context() == ctx
        with usage_context(ORG) as inner:
            assert current_usage_context() == inner and inner.session_id is None
        assert current_usage_context() == ctx
    assert current_usage_context() is None


async def test_chat_call_reports_role_and_unknown_cost(
    fake: ModelGateway, records: list[UsageRecord]
) -> None:
    """OB-2, D-12: the fake profile has no prices, so cost is 0 and cost_known false."""
    with usage_context(ORG, session_id=SESSION):
        done = await fake.complete(Role.EXTRACTOR, USER, output_type=JobPosting)
    (rec,) = records
    assert (rec.org_id, rec.session_id, rec.role) == (ORG, SESSION, Role.EXTRACTOR)
    assert rec.component == "llm" and rec.model == done.model and rec.profile == "fake"
    tokens = done.usage.input_tokens + done.usage.output_tokens
    assert rec.units == Decimal(tokens)
    assert rec.cost_usd == Decimal("0.000000") and rec.cost_known is False


async def test_chat_cost_from_config_prices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, records: list[UsageRecord]
) -> None:
    """OB-2: tokens times the litellm.<profile>.yaml prices, like the admin traces."""
    (tmp_path / "litellm.local.yaml").write_text(
        "model_list:\n"
        "  - model_name: local-small\n"
        "    model_info: {input_cost_per_token: 0.001, output_cost_per_token: 0.002}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    get_settings.cache_clear()

    def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="ok")])

    config = load_models_config(REPO / "config", "local")
    gw = ModelGateway(config, model_factory=lambda alias, cfg: FunctionModel(reply))
    alias = config.alias_for(Role.INTERVIEWER)
    with usage_context(ORG):
        done = await gw.complete(Role.INTERVIEWER, USER)
    (rec,) = records
    assert rec.session_id is None and rec.role == Role.INTERVIEWER and rec.model == alias
    assert alias == "local-small"
    assert rec.input_tokens == done.usage.input_tokens > 0
    expected = done.usage.input_tokens * 0.001 + done.usage.output_tokens * 0.002
    assert rec.cost_known and rec.cost_usd == Decimal(f"{expected:.6f}")


async def test_stream_reports_once_finished(fake: ModelGateway, records: list[UsageRecord]) -> None:
    with usage_context(ORG, session_id=SESSION):
        chunks = [c async for c in fake.stream(Role.INTERVIEWER, USER)]
    assert chunks
    (rec,) = records
    assert rec.role == Role.INTERVIEWER and rec.component == "llm"


async def test_speech_calls_report_seconds_and_characters(
    fake: ModelGateway, records: list[UsageRecord]
) -> None:
    """OB-2: stt in seconds of audio, tts in characters; no price means cost_known false."""
    with usage_context(ORG, session_id=SESSION):
        await fake.transcribe(_wav(1.5))
        await fake.synthesize("Hello there.")
        _ = [c async for c in fake.synthesize_stream("Hi.")]
    stt, tts, tts_stream = records
    assert (stt.role, stt.component, stt.units) == (Role.STT, "stt", Decimal("1.5"))
    assert (tts.role, tts.component, tts.units) == (Role.TTS, "tts", Decimal(12))
    assert tts_stream.units == Decimal(3)
    assert not any(r.cost_known for r in records)


async def test_speech_cost_from_unit_prices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: ModelGateway, records: list[UsageRecord]
) -> None:
    """D-12: a metered speech provider has a per-unit price in model_info."""
    (tmp_path / "litellm.fake.yaml").write_text(
        "model_list:\n"
        f"  - model_name: {fake.config.alias_for(Role.STT)}\n"
        "    model_info: {input_cost_per_second: 0.01}\n"
        f"  - model_name: {fake.config.alias_for(Role.TTS)}\n"
        "    model_info: {input_cost_per_character: 0.0001}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    get_settings.cache_clear()
    with usage_context(ORG):
        await fake.transcribe(_wav(2.0))
        await fake.synthesize("abcdefghij")
    stt, tts = records
    assert stt.cost_known and stt.cost_usd == Decimal("0.020000")
    assert tts.cost_known and tts.cost_usd == Decimal("0.001000")


async def test_failing_sink_never_breaks_the_call(fake: ModelGateway) -> None:
    async def broken(record: UsageRecord) -> None:
        raise RuntimeError("database down")

    previous = set_usage_sink(broken)
    try:
        with usage_context(ORG):
            done = await fake.complete(Role.EXTRACTOR, USER, output_type=JobPosting)
        assert isinstance(done.output, JobPosting)
    finally:
        set_usage_sink(previous)


@pytest.fixture
async def maker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """SQLite with only usage_events. SQLite does not enforce the foreign keys."""
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[Base.metadata.tables["usage_events"]])
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_db_sink_writes_usage_event_with_role(
    fake: ModelGateway, maker: async_sessionmaker[AsyncSession]
) -> None:
    """OB-2: one UsageEvent per call, with role and cost_known."""
    previous = set_usage_sink(make_db_usage_sink(maker))
    try:
        with usage_context(ORG, session_id=SESSION):
            await fake.complete(Role.EXTRACTOR, USER, output_type=JobPosting)
            await fake.synthesize("Hello.")
    finally:
        set_usage_sink(previous)
    async with maker() as db:
        rows = (await db.execute(select(UsageEvent).order_by(UsageEvent.created_at))).scalars()
        by_role = {r.role: r for r in rows}
    assert set(by_role) == {"extractor", "tts"}
    llm = by_role["extractor"]
    assert llm.org_id == ORG and llm.session_id == SESSION
    assert llm.component == UsageComponent.LLM and llm.cost_known is False
    assert by_role["tts"].component == UsageComponent.TTS and by_role["tts"].units == 6
