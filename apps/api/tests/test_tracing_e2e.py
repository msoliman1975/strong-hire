"""LLM tracing end to end (LT06): one sim session through every service that traces it.

All fake and in memory: the API's text channel, the worker jobs it queues (run inline), and the
sim's judge, against the in-memory exporter. Checks the trace tree, the tags that tie it to the
sim run, the redaction mode, and that a real user's session next to it makes no trace (LT-3).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import strong_core.db.engine as engine_module
import strong_core.sim as sim_module
from strong_api.auth.settings import AppEnv, get_auth_settings
from strong_core.config import get_settings
from strong_core.gateway import FakeBackend, ModelGateway
from strong_core.gateway.registry import fake_models_config
from strong_core.tracing import SpanRecord
from strong_core.tracing.testing import InMemoryExporter, trace_capture
from strong_sim.cost import CostMeter, load_prices
from strong_sim.judge import RULES
from strong_sim.runner import _traced_judge
from strong_sim.scenarios import Scenario
from strong_sim.sessions import Conversation
from strong_sim.transcript import Line
from strong_worker.scoring import jobs as scoring_jobs

from .conftest import sign_in
from .test_sessions_api import ready_job
from .test_sim_login import TOKEN, _app, _client, _env, _login

__all__ = ["trace_capture"]

RUN = "20261105-e2e-run"
ANSWER = "I moved the Acme billing ledger to Kafka and cut reconciliation time by 40 percent."
CONFIG = {
    "interview_type": "behavioral",
    "difficulty": "realistic",
    "mode": "realistic",
    "duration_min": 45,
    "level": "senior",
}


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> Any:
    sim_module._sim_orgs.clear()
    get_auth_settings.cache_clear()
    yield
    sim_module._sim_orgs.clear()
    get_settings.cache_clear()
    get_auth_settings.cache_clear()


def _dump(span: SpanRecord) -> str:
    return json.dumps(
        {"a": span.attributes, "i": span.inputs, "o": span.outputs}, default=str, sort_keys=True
    )


def _judge_gateway(fake_fixtures: Path) -> ModelGateway:
    folder = fake_fixtures / "judge"
    folder.mkdir(parents=True, exist_ok=True)
    verdict = {"rules": [{"rule": r, "verdict": "pass", "reason": "ok"} for r in RULES]}
    (folder / "JudgeVerdict.json").write_text(json.dumps(verdict), "utf-8")
    return ModelGateway(fake_models_config(), fake=FakeBackend(fake_fixtures))


async def test_lt06_a_sim_session_is_traced_across_api_worker_and_judge(
    monkeypatch: pytest.MonkeyPatch,
    sessionmaker: async_sessionmaker[AsyncSession],
    queue: Any,
    fake_fixtures: Path,
    trace_capture: InMemoryExporter,
) -> None:
    """LT-2, LT-3, LT-4, LT-6, LT-7, LT-9, LT-14 together, for one redacted sim session."""
    _env(
        monkeypatch,
        APP_ENV=AppEnv.STAGING.value,
        SESSION_SECRET="k" * 40,
        SIM_ENABLED="true",
        SIM_TOKEN=TOKEN,
        SIM_EMAIL="sim@example.com",
    )
    get_settings.cache_clear()
    # The worker's lookup opens its own database session (in production, from DATABASE_URL).
    monkeypatch.setattr(engine_module, "get_sessionmaker", lambda: sessionmaker)
    headers = {"X-Sim-Run": RUN, "X-Sim-Scenario": "pasted-cv", "X-Sim-Trace-Content": "redacted"}

    async for http in _client(_app(sessionmaker, queue)):
        assert (await _login(http)).status_code == 204
        job = await ready_job(http, fake_fixtures)
        trace_capture.clear()
        made = await http.post(
            "/sessions",
            json={"job_target_id": job["id"], "config": CONFIG, "channel": "text"},
            headers=headers,
        )
        assert made.status_code == 201, made.text
        sid = made.json()["id"]
        assert (await http.post(f"/sessions/{sid}/text/open")).status_code == 200
        for _ in range(2):
            turn = await http.post(f"/sessions/{sid}/text/turn", json={"text": ANSWER})
            assert turn.status_code == 200, turn.text
        queue.run_jobs = False  # scoring is queued on end; run it as the worker would
        assert (await http.post(f"/sessions/{sid}/end")).status_code == 200
        queue.run_jobs = True
        (function, _, kwargs) = queue.enqueued[-1]
        assert function == "score_session"
        await scoring_jobs.score_session(queue.ctx, **kwargs)

    # A real user's session next to it, with tracing on and the sim headers sent (LT-3).
    before = len(trace_capture.traces)
    _env(monkeypatch, SIM_ENABLED="true", SIM_EMAIL="sim@example.com")  # local: dev login
    get_settings.cache_clear()
    async for http in _client(_app(sessionmaker, queue)):
        await sign_in(http, "jane@example.com")
        real_job = await ready_job(http, fake_fixtures)
        real = await http.post(
            "/sessions",
            json={"job_target_id": real_job["id"], "config": {**CONFIG, "duration_min": 10},
                  "channel": "text"},
            headers=headers,
        )  # fmt: skip
        assert real.status_code == 201, real.text
        real_sid = real.json()["id"]
        assert (await http.post(f"/sessions/{real_sid}/text/open")).status_code == 200
        turn = await http.post(f"/sessions/{real_sid}/text/turn", json={"text": ANSWER})
        assert turn.status_code == 200, turn.text
    assert len(trace_capture.traces) == before, "a real user's session was traced"

    # The sim's judge, as the runner calls it, in its own trace.
    scenario = Scenario(id="pasted-cv", quality="strong", candidate_name="Ada Venn", cv_text="CV")
    conv = Conversation()
    conv.lines.extend(
        [Line(speaker="interviewer", text="Tell me about a migration.", start_ms=0, end_ms=900),
         Line(speaker="candidate", text=ANSWER, start_ms=2000, end_ms=9000)]
    )  # fmt: skip
    verdict = await _traced_judge(
        scenario, conv, _judge_gateway(fake_fixtures), CostMeter(load_prices()), sid, RUN
    )
    assert verdict.passed

    traces = trace_capture.traces
    by_name: dict[str, list[Any]] = {}
    for t in traces:
        by_name.setdefault(t.root.name, []).append(t)
    assert set(by_name) == {"build_interviewer_brief", "turn", "score_session", "judge"}
    assert [t.root.attributes["turn.index"] for t in by_name["turn"]] == [0, 1, 2]
    services = {t.root.name: t.tags.service for t in traces}
    assert services == {
        "build_interviewer_brief": "worker",
        "turn": "api",
        "score_session": "worker",
        "judge": "sim",
    }
    for t in traces:  # one session, one run, one content mode (LT-7, LT-14)
        assert t.tags.session_id == sid and t.tags.sim_run_id == RUN
        assert t.tags.content == "redacted"
        assert all(c.name.startswith("gateway.") for c in t.root.children)
        assert t.root.children, t.root.name
    roles = {c.attributes["role"] for t in traces for c in t.root.children}
    assert {"planner", "interviewer", "scorer", "judge"} <= roles
    for t in traces:  # LT-4: no answer text anywhere in a redacted trace
        for s in t.spans():
            assert "Kafka" not in _dump(s) and "Acme" not in _dump(s), (t.root.name, s.name)
    for t in by_name["turn"]:
        calls = [c for c in t.root.children if c.name == "gateway.interviewer"]
        assert calls and all("sha256" in str(c.inputs) for c in calls)
