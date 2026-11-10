"""Phase 2, real users' sessions (LT-16 to LT-23, LT-31): who is traced, and what is kept."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import strong_core.sim as sim_module
from strong_core import runtime_settings as rs
from strong_core.config import Settings, get_settings
from strong_core.db.models import Base, InterviewSession, JobTarget, Org, Resume, User
from strong_core.gateway import Message, Role, build_gateway
from strong_core.schemas.enums import AuthProvider, Difficulty, InterviewType, Mode
from strong_core.tracing import (
    TraceTags,
    record_turn_content,
    set_exporter_override,
    trace_context,
    turn_span,
)
from strong_core.tracing.prod import delete_org_traces, org_filter, prune_prod
from strong_core.tracing.scrub import Scrubber
from strong_core.tracing.sessions import in_sample, trace_tags_for, turn_content_allowed
from strong_core.tracing.testing import InMemoryExporter

ANSWER = "I'm Jane Roe; at Acme Corporation I moved billing to Kafka. Mail jane@roe.dev."


@pytest.fixture
def exporter(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemoryExporter]:
    for key in ("LLM_TRACING_PROD", "LLM_TRACING_PROD_CONTENT", "LLM_TRACING_SAMPLE",
                "LLM_TRACING_DEV", "SIM_ENABLED"):  # fmt: skip
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    rs.clear_cache()
    sim_module._sim_orgs.clear()
    memory = InMemoryExporter()
    previous = set_exporter_override(memory)
    yield memory
    set_exporter_override(previous)
    get_settings.cache_clear()
    rs.clear_cache()


def _flags(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _user(db: AsyncSession, *, consent: bool = False) -> tuple[uuid.UUID, uuid.UUID]:
    org = Org(name="o")
    db.add(org)
    await db.flush()
    user = User(
        org_id=org.id,
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        auth_provider=AuthProvider.EMAIL,
        full_name="Jane Roe",
        tracing_consent=consent,
    )
    db.add(user)
    await db.flush()
    posting = {"company_name": "Globex", "title": "SWE"}
    target = JobTarget(org_id=org.id, user_id=user.id, parsed_json=posting)
    resume = {"roles": [{"title": "SWE", "company": "Acme Corporation"}]}
    db.add_all([target, Resume(org_id=org.id, user_id=user.id, parsed_json=resume)])
    await db.flush()
    session = InterviewSession(
        org_id=org.id,
        job_target_id=target.id,
        type=InterviewType.BEHAVIORAL,
        difficulty=Difficulty.REALISTIC,
        mode=Mode.REALISTIC,
        duration_min=30,
    )
    db.add(session)
    await db.commit()
    return org.id, session.id


# --- LT-16, LT-18, LT-19: who is traced -----------------------------------------------------


async def test_lt16_real_users_are_untraced_until_the_prod_flag(
    exporter: InMemoryExporter, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LT-16: rules out tracing a real user while LLM_TRACING_PROD is off (the default)."""
    org, sid = await _user(db, consent=True)
    assert await trace_tags_for(org_id=org, session_id=sid, service="api", db=db) is None
    _flags(monkeypatch, LLM_TRACING_PROD="on")
    tags = await trace_tags_for(org_id=org, session_id=sid, service="api", db=db)
    assert tags is not None
    assert (tags.experiment, tags.content, tags.turn_content) == ("prod", "metadata", False)


async def test_lt18_production_traces_carry_org_and_session(
    exporter: InMemoryExporter, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LT-18: every production trace can be found by org after its rows are gone."""
    _flags(monkeypatch, LLM_TRACING_PROD="on")
    org, sid = await _user(db)
    tags = await trace_tags_for(org_id=org, session_id=sid, service="worker", db=db)
    assert tags is not None
    assert tags.as_tags()["org_id"] == str(org) and tags.as_tags()["session_id"] == str(sid)
    assert "sim_run_id" not in tags.as_tags()


async def test_lt19_pause_switch_stops_production_tracing(
    exporter: InMemoryExporter, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LT-19: the Controls page switch stops tracing real users without a deploy."""
    _flags(monkeypatch, LLM_TRACING_PROD="on")
    org, sid = await _user(db)
    await rs.set(db, rs.SettingKey.LLM_TRACING_PAUSED, True, actor="admin@example.com")
    await db.commit()
    rs.clear_cache()
    assert await trace_tags_for(org_id=org, session_id=sid, service="api", db=db) is None


def test_lt19_sampling_is_per_session_and_stable() -> None:
    """LT-19: a session is traced whole or not at all, and the rate holds overall."""
    ids = [uuid.uuid4() for _ in range(2000)]
    chosen = [i for i in ids if in_sample(i, 0.25)]
    assert all(in_sample(i, 0.25) for i in chosen)  # the same answer every time
    assert 0.20 < len(chosen) / len(ids) < 0.30
    assert all(in_sample(i, 1.0) for i in ids[:10]) and not any(in_sample(i, 0.0) for i in ids[:10])


async def test_lt19_a_session_outside_the_sample_is_not_traced(
    exporter: InMemoryExporter, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LT-19: LLM_TRACING_SAMPLE=0 traces no real session."""
    _flags(monkeypatch, LLM_TRACING_PROD="on", LLM_TRACING_SAMPLE="0")
    org, sid = await _user(db)
    assert await trace_tags_for(org_id=org, session_id=sid, service="api", db=db) is None


# --- LT-20: consent ---------------------------------------------------------------------------


async def test_lt20_turn_content_needs_the_content_flag_and_consent(
    exporter: InMemoryExporter, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LT-20: rules out keeping content for a user who did not consent, or before gate 2."""
    _flags(monkeypatch, LLM_TRACING_PROD="on")
    yes_org, yes_sid = await _user(db, consent=True)
    no_org, no_sid = await _user(db, consent=False)
    tags = await trace_tags_for(org_id=yes_org, session_id=yes_sid, service="api", db=db)
    assert tags is not None and not tags.turn_content  # content flag still off
    assert not await turn_content_allowed(yes_org, db)
    _flags(monkeypatch, LLM_TRACING_PROD="on", LLM_TRACING_PROD_CONTENT="on")
    tags = await trace_tags_for(org_id=yes_org, session_id=yes_sid, service="api", db=db)
    assert tags is not None and tags.turn_content
    assert await turn_content_allowed(yes_org, db)
    tags = await trace_tags_for(org_id=no_org, session_id=no_sid, service="api", db=db)
    assert tags is not None and not tags.turn_content
    assert not await turn_content_allowed(no_org, db)


async def test_lt20_consent_defaults_off(db: AsyncSession) -> None:
    """LT-20: a new user has tracing consent off."""
    org = Org(name="o")
    db.add(org)
    await db.flush()
    user = User(org_id=org.id, email="new@example.com", auth_provider=AuthProvider.EMAIL)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    assert user.tracing_consent is False and user.tracing_consent_at is None


# --- LT-17: no text in a production span ----------------------------------------------------


async def test_lt17_a_real_users_spans_hold_no_text_and_no_hash(
    exporter: InMemoryExporter, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LT-17: rules out a real user's answer, its hash or an error message in a metadata span,
    even with consent."""
    _flags(monkeypatch, LLM_TRACING_PROD="on", LLM_TRACING_PROD_CONTENT="on")
    org, sid = await _user(db, consent=True)
    tags = await trace_tags_for(org_id=org, session_id=sid, service="api", db=db)
    gateway = build_gateway(Settings(model_profile="fake"))
    with trace_context(tags), turn_span("text", 1):  # type: ignore[arg-type]
        _ = [
            c
            async for c in gateway.stream(Role.INTERVIEWER, [Message(role="user", content=ANSWER)])
        ]
        await gateway.synthesize(ANSWER)
    (trace,) = exporter.traces
    dump = json.dumps([[s.attributes, s.inputs, s.outputs] for s in trace.spans()], default=str)
    for leak in ("Jane", "Acme", "Kafka", "jane@roe.dev", "sha256", "error.message"):
        assert leak not in dump, leak
    call = trace.root.children[0]
    assert call.inputs == {"messages": [{"role": "user", "len": len(ANSWER)}]}


# --- LT-22, LT-23: scrubbed content in its own trace -------------------------------------------


async def test_lt22_scrubber_removes_name_companies_email_and_phone(db: AsyncSession) -> None:
    """LT-22: rules out the user's name, their companies, emails and phones in kept content."""
    org, _ = await _user(db, consent=True)
    scrubber = await Scrubber.for_org(db, org)
    out = scrubber.scrub(ANSWER + " Call +1 415 555 0100. Globex next? jane said ACME corporation.")
    for leak in ("Jane", "Roe", "Acme", "ACME", "Globex", "jane@roe.dev", "555"):
        assert leak not in out, (leak, out)
    assert "[name]" in out and "[company]" in out and "Kafka" in out


def test_lt22_scrubber_keeps_words_that_only_contain_a_name() -> None:
    """LT-22: word boundaries; a short or partial match is left alone."""
    scrubber = Scrubber(names=["Al"], companies=["Box"])
    assert (
        scrubber.scrub("Alice used Boxes; Al shipped Box.")
        == "Alice used Boxes; [name] shipped [company]."
    )


async def test_lt23_turn_content_is_its_own_scrubbed_trace(
    exporter: InMemoryExporter, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LT-23: content goes into a turn.content trace tagged content=turns, never the turn trace."""
    _flags(monkeypatch, LLM_TRACING_PROD="on", LLM_TRACING_PROD_CONTENT="on")
    org, sid = await _user(db, consent=True)
    tags = await trace_tags_for(org_id=org, session_id=sid, service="api", db=db)
    scrubber = await Scrubber.for_org(db, org)
    assert record_turn_content(tags, 3, "text", "Tell me more, Jane.", ANSWER, scrubber.scrub)
    (trace,) = exporter.traces
    assert trace.root.name == "turn.content" and trace.tags.as_tags()["content"] == "turns"
    assert trace.tags.as_tags()["org_id"] == str(org) and trace.root.attributes["turn.index"] == 3
    stored = json.dumps([trace.root.inputs, trace.root.outputs])
    assert "Kafka" in stored and "Jane" not in stored and "Acme" not in stored


async def test_lt23_no_content_trace_without_consent(
    exporter: InMemoryExporter, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LT-21, LT-23: rules out keeping a non-consenting user's turn."""
    _flags(monkeypatch, LLM_TRACING_PROD="on", LLM_TRACING_PROD_CONTENT="on")
    org, sid = await _user(db, consent=False)
    tags = await trace_tags_for(org_id=org, session_id=sid, service="api", db=db)
    assert not record_turn_content(tags, 1, "text", "Hi.", ANSWER, str.strip)
    assert not record_turn_content(None, 1, "text", "Hi.", ANSWER, str.strip)
    assert exporter.traces == []


# --- LT-31: fail closed -----------------------------------------------------------------------


async def test_lt31_any_lookup_error_means_not_traced(
    exporter: InMemoryExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LT-31: a broken database never turns tracing on and never raises."""
    _flags(monkeypatch, LLM_TRACING_PROD="on", LLM_TRACING_PROD_CONTENT="on")

    class Broken:
        async def scalar(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("db down")

        async def execute(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("db down")

    org, sid = uuid.uuid4(), uuid.uuid4()
    assert await trace_tags_for(org_id=org, session_id=sid, service="api", db=Broken()) is None  # type: ignore[arg-type]
    assert await turn_content_allowed(org, Broken()) is False  # type: ignore[arg-type]

    def boom(text: str) -> str:
        raise ValueError("scrub failed")

    tags = TraceTags(session_id=str(sid), org_id=str(org), content="metadata", turn_content=True)
    assert record_turn_content(tags, 1, "text", "a", "b", boom) is False
    assert exporter.traces == []


# --- deletion helpers (used by PT03) ------------------------------------------------------------


class FakeStore:
    def __init__(self, traces: dict[str, dict[str, Any]]) -> None:
        self.traces = traces
        self.filters: list[str] = []

    def experiment_id(self, name: str) -> str | None:
        return "9" if name == "prod" else None

    def trace_ids(self, experiment_id: str, filter_string: str) -> list[str]:
        self.filters.append(filter_string)
        out = []
        for tid, t in self.traces.items():
            if f"tags.org_id = '{t['org']}'" not in filter_string:
                continue
            if "tags.content = 'turns'" in filter_string and t["content"] != "turns":
                continue
            out.append(tid)
        return out[:2]  # small pages, to exercise the loop

    def delete(self, experiment_id: str, trace_ids: list[str]) -> int:
        for tid in trace_ids:
            del self.traces[tid]
        return len(trace_ids)

    def delete_before(self, experiment_id: str, before_ms: int) -> int:
        return 0


def test_lt24_lt25_delete_org_traces_by_scope(exporter: InMemoryExporter) -> None:
    """LT-24: withdrawal deletes only turn.content; LT-25: account deletion deletes everything."""
    org, other = uuid.uuid4(), uuid.uuid4()
    traces = {
        f"t{i}": {"org": str(org), "content": "turns" if i % 2 else "metadata"} for i in range(5)
    }
    traces["keep"] = {"org": str(other), "content": "turns"}
    store = FakeStore(traces)
    assert delete_org_traces(org, "content", store) == 2
    assert {t["content"] for k, t in store.traces.items() if k != "keep"} == {"metadata"}
    assert delete_org_traces(org, "all", store) == 3
    assert list(store.traces) == ["keep"]


def test_lt25_a_trace_that_will_not_delete_raises_for_a_retry() -> None:
    """LT-26: the job must not report success while traces remain."""

    class Stuck(FakeStore):
        def delete(self, experiment_id: str, trace_ids: list[str]) -> int:
            return 0

    org = uuid.uuid4()
    with pytest.raises(RuntimeError):
        delete_org_traces(org, "all", Stuck({"t": {"org": str(org), "content": "metadata"}}))


def test_lt27_prune_uses_30_and_90_days() -> None:
    """LT-27: content older than 30 days, everything older than 90."""
    seen: list[Any] = []

    class Recording(FakeStore):
        def trace_ids(self, experiment_id: str, filter_string: str) -> list[str]:
            seen.append(filter_string)
            return []

        def delete_before(self, experiment_id: str, before_ms: int) -> int:
            seen.append(before_ms)
            return 4

    now = 1_800_000_000.0
    assert prune_prod(30, 90, Recording({}), now_s=now) == {"content": 0, "metadata": 4}
    assert seen == [
        f"tags.content = 'turns' AND attributes.timestamp_ms < {int((now - 30 * 86400) * 1000)}",
        int((now - 90 * 86400) * 1000),
    ]
    with pytest.raises(ValueError):
        prune_prod(90, 30, Recording({}))


def test_org_filter_quotes_values() -> None:
    org = uuid.uuid4()
    assert org_filter(org, "all") == f"tags.org_id = '{org}'"
    assert org_filter(org, "content").endswith(" AND tags.content = 'turns'")
