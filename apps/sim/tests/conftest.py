"""Shared fakes for the AI candidate tests: a fake Strong Hire API and a fake model gateway."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from strong_core.gateway import FakeBackend, ModelGateway
from strong_core.gateway.registry import fake_models_config
from strong_sim.judge import RULES


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
        self.postings: list[str] = []
        self.resume_texts: list[str] = []
        self.reject_postings: str | None = None  # the extractor's reason, to fail every posting

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
            body = json.loads(request.content)
            self.postings.append(body["text"])
            status = "pending" if self.reject_postings else "extracted"
            jt = {"id": str(uuid.uuid4()), "status": status, "stage": body["stage"]}
            if not self.reject_postings:
                self.targets.append({"job_target": jt, "gap_status": "ready"})
            job = {"id": "extract-1", "status": "queued"}
            return httpx.Response(202, json={"job_target": jt, "job": job})
        if path.startswith("/job-targets/") and "/jobs/" in path:
            failed = {"id": "extract-1", "status": "failed", "error": self.reject_postings}
            return httpx.Response(
                200, json=failed if self.reject_postings else {"status": "complete"}
            )
        if path.startswith("/job-targets/") and path.endswith("/gap-analysis"):
            return httpx.Response(202 if method == "POST" else 200, json={"status": "ready"})
        if path.startswith("/job-targets/"):
            return httpx.Response(
                200, json={"status": "pending" if self.reject_postings else "extracted"}
            )
        if path == "/resumes":
            self.resume_texts.append(parse_qs(request.content.decode())["text"][0])
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
def fake_api() -> type[FakeApi]:
    return FakeApi


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
