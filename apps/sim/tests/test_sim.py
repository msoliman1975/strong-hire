"""The AI candidate (P13): scenarios, pairwise selection, the text run loop, judge, report, files.

No network: the API is an httpx.MockTransport and the models are the fake backend.
"""

from __future__ import annotations

import itertools
import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest

from strong_core.gateway import FakeBackend, ModelGateway
from strong_core.gateway.registry import fake_models_config
from strong_sim.candidate import SILENCE, clean
from strong_sim.client import AppClient
from strong_sim.cost import CostLimitError, CostMeter, estimate, load_prices
from strong_sim.judge import RULES
from strong_sim.report import SessionRow, order_breaks
from strong_sim.runner import run_suite
from strong_sim.scenarios import Scenario, Suite, list_suites, load_suite, pairwise
from strong_sim.settings import SimSettings

# ---------------------------------------------------------------- scenarios


def test_every_suite_loads_and_ids_are_unique() -> None:
    names = list_suites()
    assert {"text-smoke", "voice-smoke", "text-behaviors"} <= set(names)
    for name in names:
        suite = load_suite(name)
        assert suite.scenarios, name


def test_pairwise_covers_every_pair_and_is_stable() -> None:
    dims = {"a": [1, 2, 3], "b": ["x", "y"], "c": [True, False], "d": ["p", "q", "r", "s"]}
    rows = pairwise(dims, seed=3)
    for (n1, v1s), (n2, v2s) in itertools.combinations(dims.items(), 2):
        for v1, v2 in itertools.product(v1s, v2s):
            assert any(r[n1] == v1 and r[n2] == v2 for r in rows), (n1, v1, n2, v2)
    assert rows == pairwise(dims, seed=3)
    assert len(rows) < len(list(itertools.product(*dims.values())))  # 48


def test_voice_only_behavior_needs_voice() -> None:
    with pytest.raises(ValueError, match="voice"):
        Scenario(id="x", channel="text", behavior="interrupts").check()


def test_clean_keeps_only_spoken_words() -> None:
    assert clean('"(smiles) Sure, happy to."') == "Sure, happy to."
    assert clean("Candidate: I led it.") == "I led it."
    assert clean(" [silence] ") == SILENCE


# ---------------------------------------------------------------- cost


def test_cost_meter_stops_at_the_limit() -> None:
    from strong_core.gateway import Completion, Role, TokenUsage

    meter = CostMeter({"m": (1.0, 2.0)}, limit_usd=0.01)
    done = Completion("x", Role.CANDIDATE, "m", "fake", (), TokenUsage(1000, 1000))
    meter.add(done)
    assert meter.total_usd == pytest.approx(0.003)
    with pytest.raises(CostLimitError):
        for _ in range(5):
            meter.add(done)


def test_estimate_counts_every_session() -> None:
    est = estimate([30, 30, 10], load_prices())
    assert est["total_usd"] > 0
    assert est["total_usd"] == pytest.approx(
        est["candidate_usd"] + est["judge_usd"] + est["main_server_usd"]
    )


# ---------------------------------------------------------------- scorer order check


def _row(sid: str, quality: str, signal: str) -> SessionRow:
    return SessionRow(
        scenario_id=sid, channel="text", interview_type="behavioral", difficulty="realistic",
        mode="realistic", duration_min=30, resume="backend-senior", quality=quality,
        behavior="normal", status="ok", hire_signal=signal,
    )  # fmt: skip


def test_order_breaks_flags_a_weak_candidate_above_a_strong_one() -> None:
    good = [_row("s", "strong", "Hire"), _row("a", "average", "Lean Hire"),
            _row("w", "weak", "No Hire")]  # fmt: skip
    assert order_breaks(good) == []
    bad = [_row("s", "strong", "Lean No Hire"), _row("w", "weak", "Hire")]
    assert len(order_breaks(bad)) == 1


# ---------------------------------------------------------------- a full text run, offline


class FakeApi:
    """Just enough of the Strong Hire API for one text session per scenario."""

    def __init__(self, token: str, turns_per_session: int = 3) -> None:
        self.token = token
        self.turns_per_session = turns_per_session
        self.signed_in = False
        self.sessions: dict[str, dict[str, Any]] = {}
        self.targets: list[dict[str, Any]] = []
        self.candidate_texts: list[str] = []
        self.remaining_usd = 5.0
        self.reported_usd: list[float] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path.removeprefix("/api"), request.method
        if path == "/auth/sim-login":
            ok = request.headers.get("x-sim-token") == self.token
            self.signed_in = ok
            return httpx.Response(204 if ok else 404)
        if not self.signed_in:
            return httpx.Response(401)
        if path == "/auth/sim-budget":
            left = self.remaining_usd
            return httpx.Response(200, json={"limit_usd": 5.0, "remaining_usd": left})
        if path == "/auth/sim-spend":
            self.reported_usd.append(json.loads(request.content)["usd"])
            return httpx.Response(204)
        if path == "/auth/me":
            return httpx.Response(200, json={"status": "signed_in", "user": {"email": "sim@x"}})
        if path == "/job-targets" and method == "GET":
            return httpx.Response(200, json=self.targets)
        if path == "/job-targets" and method == "POST":
            stage = json.loads(request.content)["stage"]
            jt = {"id": str(uuid.uuid4()), "status": "extracted", "stage": stage}
            self.targets.append({"job_target": jt, "gap_status": "ready"})
            return httpx.Response(202, json={"job_target": jt, "job": None})
        if path.startswith("/job-targets/") and path.endswith("/gap-analysis"):
            return httpx.Response(202 if method == "POST" else 200, json={"status": "ready"})
        if path.startswith("/job-targets/"):
            return httpx.Response(200, json={"status": "extracted"})
        if path == "/resumes":
            return httpx.Response(202, json={"resume": {"id": str(uuid.uuid4())}, "job": None})
        if path.startswith("/resumes/"):
            return httpx.Response(200, json={"status": "extracted"})
        if path == "/sessions":
            sid = str(uuid.uuid4())
            self.sessions[sid] = {"id": sid, "status": "created", "brief_ready": True, "n": 0}
            return httpx.Response(201, json=self.sessions[sid])
        sid = path.split("/")[2]
        session = self.sessions[sid]
        if path.endswith("/text/open"):
            session["status"] = "in_progress"
            return httpx.Response(200, json=self._turns("Hello, tell me about yourself.", False))
        if path.endswith("/text/turn"):
            self.candidate_texts.append(json.loads(request.content)["text"])
            session["n"] += 1
            ended = session["n"] >= self.turns_per_session
            if ended:
                session["status"] = "scoring"
            return httpx.Response(200, json=self._turns("Thanks. Next question?", ended))
        if path.endswith("/debrief"):
            card = {"hire_signal": "Lean Hire"}
            return httpx.Response(200, json={"status": "ready", "scorecard": card})
        if path.endswith("/end"):
            session["status"] = "scoring"
            return httpx.Response(200, json=session)
        return httpx.Response(200, json=session)

    @staticmethod
    def _turns(text: str, ended: bool) -> dict[str, Any]:
        turn = {"speaker": "interviewer", "phase": "core", "text": text, "start_ms": 0,
                "end_ms": 1, "question_ref": None}  # fmt: skip
        return {"turns": [turn], "ended": ended, "phase": "core"}


@pytest.fixture
def fake_gateway(tmp_path: Path) -> ModelGateway:
    fixtures = tmp_path / "fixtures"
    (fixtures / "candidate").mkdir(parents=True)
    (fixtures / "candidate" / "text.txt").write_text("I led the billing rebuild.", "utf-8")
    (fixtures / "judge").mkdir()
    verdict = {
        "rules": [{"rule": r, "verdict": "pass", "reason": "ok"} for r in RULES],
        "problems": [],
    }
    (fixtures / "judge" / "JudgeVerdict.json").write_text(json.dumps(verdict), "utf-8")
    return ModelGateway(fake_models_config(), fake=FakeBackend(fixtures))


async def test_text_run_writes_every_file_and_a_report(
    tmp_path: Path, fake_gateway: ModelGateway
) -> None:
    token = "t" * 40
    api = FakeApi(token)
    settings = SimSettings(
        base_url="https://sim.test/api", token=token, out_dir=tmp_path / "runs", upload_target=""
    )
    http = httpx.AsyncClient(base_url=settings.base_url, transport=httpx.MockTransport(api))
    client = AppClient(settings, http)
    suite = Suite(
        name="t",
        scenarios=[
            Scenario(id="a", quality="strong", candidate_name="Ada Venn"),
            Scenario(id="b", quality="weak", candidate_name="Cal Dunmore"),
        ],
    )
    meter = CostMeter(load_prices())
    run_dir, info = await run_suite(suite, settings, fake_gateway, meter, "run-1", client)

    assert info["sessions"] == 2 and info["sessions_ok"] == 2
    assert info["sessions_all_rules_pass"] == 2
    assert len(api.targets) == 1  # one job per resume fixture, reused
    assert api.candidate_texts == ["I led the billing rebuild."] * 6
    for sid in api.sessions:
        folder = run_dir / sid
        for name in ("transcript.json", "transcript.txt", "judge.json", "debrief.json",
                     "meta.json"):  # fmt: skip
            assert (folder / name).exists(), name
        lines = json.loads((folder / "transcript.json").read_text("utf-8"))
        assert [x["speaker"] for x in lines][:2] == ["interviewer", "candidate"]
        meta = json.loads((folder / "meta.json").read_text("utf-8"))
        assert meta["candidate_model"] == "fake-candidate"
        assert "judge/transcript.v1" in meta["prompts"]
    report = json.loads((run_dir / "report.json").read_text("utf-8"))
    assert {s["hire_signal"] for s in report["sessions"]} == {"Lean Hire"}
    assert "Sim run run-1" in (run_dir / "report.html").read_text("utf-8")
    assert (run_dir / "scenarios.yaml").exists()


async def test_wrong_token_stops_before_any_session(
    tmp_path: Path, fake_gateway: ModelGateway
) -> None:
    api = FakeApi("t" * 40)
    settings = SimSettings(base_url="https://sim.test/api", token="w" * 40, out_dir=tmp_path)
    http = httpx.AsyncClient(base_url=settings.base_url, transport=httpx.MockTransport(api))
    suite = Suite(name="t", scenarios=[Scenario(id="a")])
    with pytest.raises(Exception, match="sim sign-in failed"):
        await run_suite(suite, settings, fake_gateway, CostMeter(load_prices()), "r",
                        AppClient(settings, http))  # fmt: skip
    assert api.sessions == {}


async def test_candidate_retries_after_a_rate_limit(
    monkeypatch: pytest.MonkeyPatch, fake_gateway: ModelGateway
) -> None:
    """A free tier answers 429 now and then; the candidate waits and tries again."""
    from strong_sim import candidate as candidate_module
    from strong_sim.candidate import Candidate, Pacer
    from strong_sim.transcript import Line

    class RateLimitedError(Exception):
        status_code = 429

    calls = {"n": 0}
    real = fake_gateway.complete

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimitedError("429")
        return await real(*args, **kwargs)

    monkeypatch.setattr(candidate_module, "RATE_LIMIT_WAIT_S", 0.0)
    monkeypatch.setattr(fake_gateway, "complete", flaky)
    cand = Candidate(Scenario(id="a", candidate_name="Ada Venn"), fake_gateway,
                     CostMeter(load_prices()), Pacer(retries=2))  # fmt: skip
    line = Line(speaker="interviewer", text="Hi", start_ms=0, end_ms=0)
    assert await cand.reply([line]) == "I led the billing rebuild."
    assert calls["n"] == 2


async def test_a_failed_session_keeps_its_transcript(
    tmp_path: Path, fake_gateway: ModelGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A candidate model failure mid-session keeps the lines so far and ends the session."""
    token = "t" * 40
    api = FakeApi(token, turns_per_session=5)
    settings = SimSettings(base_url="https://sim.test/api", token=token, out_dir=tmp_path)
    http = httpx.AsyncClient(base_url=settings.base_url, transport=httpx.MockTransport(api))
    calls = {"n": 0}
    real = fake_gateway.complete

    async def breaks_on_third(role: Any, *args: Any, **kwargs: Any) -> Any:
        if str(role) == "candidate":
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("provider down")
        return await real(role, *args, **kwargs)

    monkeypatch.setattr(fake_gateway, "complete", breaks_on_third)
    suite = Suite(name="t", scenarios=[Scenario(id="a", candidate_name="Ada Venn")])
    run_dir, info = await run_suite(suite, settings, fake_gateway, CostMeter(load_prices()), "r",
                                    AppClient(settings, http))  # fmt: skip
    assert info["sessions_error"] == 1
    (sid,) = api.sessions
    lines = json.loads((run_dir / sid / "transcript.json").read_text("utf-8"))
    assert [x["speaker"] for x in lines] == ["interviewer", "candidate"] * 2 + ["interviewer"]
    assert api.sessions[sid]["status"] == "scoring"  # ended by the harness


async def test_run_stops_when_the_daily_budget_is_used_up(
    tmp_path: Path, fake_gateway: ModelGateway
) -> None:
    """P13: the AI-to-AI budget is checked before each session; nothing starts without money."""
    token = "t" * 40
    api = FakeApi(token)
    api.remaining_usd = 0.01
    settings = SimSettings(base_url="https://sim.test/api", token=token, out_dir=tmp_path)
    http = httpx.AsyncClient(base_url=settings.base_url, transport=httpx.MockTransport(api))
    suite = Suite(name="t", scenarios=[Scenario(id="a", candidate_name="Ada Venn")])
    _, info = await run_suite(suite, settings, fake_gateway, CostMeter(load_prices()), "r",
                              AppClient(settings, http))  # fmt: skip
    assert api.sessions == {}
    assert "daily AI-to-AI budget" in info["stopped"]
