"""HTTP client for the Strong Hire API, used the way the web app uses it (P13).

Job targets are reused across runs: each one is tagged with stage "sim:<resume fixture>", so a
run creates the job, the resume and the gap analysis only once per fixture.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from strong_sim.candidate import fixture_text
from strong_sim.scenarios import Scenario
from strong_sim.settings import SimSettings

STAGE_PREFIX = "sim:"
log = logging.getLogger("strong_sim")

POLL_S = 2.0
BUSY_RETRIES = 30
FAILED_RETRIES = 2


class ApiError(RuntimeError):
    pass


class AppClient:
    def __init__(self, settings: SimSettings, http: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.http = http or httpx.AsyncClient(
            base_url=settings.base_url.rstrip("/"),
            timeout=settings.http_timeout_s,
            follow_redirects=False,
        )
        self._jobs: dict[str, str] = {}

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _call(self, method: str, path: str, **kw: Any) -> Any:
        resp = await self.http.request(method, path, **kw)
        if resp.status_code >= 400:
            raise ApiError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else None

    async def sign_in(self) -> dict[str, Any]:
        token = self.settings.token.get_secret_value()
        resp = await self.http.post("/auth/sim-login", headers={"X-Sim-Token": token})
        if resp.status_code != 204:
            raise ApiError(
                f"sim sign-in failed ({resp.status_code}). Is SIM_ENABLED=true on the server, "
                "and does SIM_TOKEN match?"
            )
        me: dict[str, Any] = await self._call("GET", "/auth/me")
        return me

    async def budget(self) -> dict[str, Any] | None:
        """The AI-to-AI daily budget, or None when the server has no budget route."""
        resp = await self.http.get("/auth/sim-budget")
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise ApiError(f"GET /auth/sim-budget -> {resp.status_code}: {resp.text[:300]}")
        data: dict[str, Any] = resp.json()
        return data

    async def report_spend(self, usd: float) -> None:
        """Add the candidate and judge cost to the shared daily budget."""
        if usd > 0:
            await self._call("POST", "/auth/sim-spend", json={"usd": round(usd, 6)})

    async def _wait(self, what: str, check: Any) -> Any:
        deadline = time.monotonic() + self.settings.wait_timeout_s
        while True:
            result = await check()
            if result is not None:
                return result
            if time.monotonic() > deadline:
                raise ApiError(f"timed out waiting for {what}")
            await asyncio.sleep(POLL_S)

    # ------------------------------------------------------------------ job, resume, gap

    async def job_for(self, scenario: Scenario) -> str:
        """The job target for the scenario's resume fixture, with a ready gap analysis."""
        key = scenario.resume
        if key in self._jobs:
            return self._jobs[key]
        stage = f"{STAGE_PREFIX}{key}"
        listed = await self._call("GET", "/job-targets")
        found = [
            row for row in listed
            if row["job_target"]["stage"] == stage and row["gap_status"] == "ready"
        ]  # fmt: skip
        if found:
            job_id: str = found[0]["job_target"]["id"]
        else:
            job_id = await self._new_job(scenario, stage)
        self._jobs[key] = job_id
        return job_id

    async def _new_job(self, scenario: Scenario, stage: str) -> str:
        posting = fixture_text("postings", scenario.fixture.posting)
        accepted = await self._call("POST", "/job-targets", json={"text": posting, "stage": stage})
        job_id: str = accepted["job_target"]["id"]
        resume_text = fixture_text("resumes", scenario.resume)
        resume = await self._call("POST", "/resumes", data={"text": resume_text})
        resume_id: str = resume["resume"]["id"]

        async def job_ready() -> bool | None:
            row = await self._call("GET", f"/job-targets/{job_id}")
            return True if row["status"] == "extracted" else None

        async def resume_ready() -> bool | None:
            row = await self._call("GET", f"/resumes/{resume_id}")
            return True if row["status"] == "extracted" else None

        await self._wait("the job posting to be read", job_ready)
        await self._wait("the resume to be read", resume_ready)
        await self._call(
            "POST", f"/job-targets/{job_id}/gap-analysis", json={"resume_id": resume_id}
        )

        async def gap_ready() -> bool | None:
            row = await self._call("GET", f"/job-targets/{job_id}/gap-analysis")
            if row["status"] == "failed":
                raise ApiError(f"gap analysis failed: {row.get('error')}")
            return True if row["status"] == "ready" else None

        await self._wait("the gap analysis", gap_ready)
        return job_id

    # ------------------------------------------------------------------ sessions

    async def create_session(self, scenario: Scenario, job_id: str) -> dict[str, Any]:
        body = {
            "job_target_id": job_id,
            "config": scenario.session_config().model_dump(mode="json"),
            "channel": scenario.channel,
        }
        record: dict[str, Any] = await self._call("POST", "/sessions", json=body)
        sid = record["id"]

        async def brief_ready() -> dict[str, Any] | None:
            row: dict[str, Any] = await self._call("GET", f"/sessions/{sid}")
            if row["status"] == "failed":
                reason = row.get("failure_reason") or "no reason given"
                raise ApiError(f"the session failed before it started: {reason}")
            return row if row["brief_ready"] else None

        ready: dict[str, Any] = await self._wait("the interview plan", brief_ready)
        return ready

    async def text_open(self, sid: str) -> dict[str, Any]:
        out: dict[str, Any] = await self._call("POST", f"/sessions/{sid}/text/open")
        return out

    async def text_turn(self, sid: str, text: str) -> dict[str, Any]:
        """Send one candidate turn, and retry when the server says so.

        409: the last reply is still being made. 503 (the turn save failed) and 504 (the reply
        passed the server's time limit): the turn was rolled back, so the same text is sent again,
        at most FAILED_RETRIES times.
        """
        path = f"/sessions/{sid}/text/turn"
        failed = 0
        for _ in range(BUSY_RETRIES):
            # The send time, so a turn that never gets an answer can be found in the server logs.
            log.info("text/turn sent: session %s, %d characters", sid, len(text))
            resp = await self.http.post(path, json={"text": text[:4000]})
            if resp.status_code in (503, 504) and failed < FAILED_RETRIES:
                failed += 1
                log.warning("text/turn %s: %d, retry %d", sid, resp.status_code, failed)
            elif resp.status_code != 409:
                break
            await asyncio.sleep(POLL_S)
        if resp.status_code >= 400:
            raise ApiError(f"POST {path} -> {resp.status_code}: {resp.text[:300]}")
        out: dict[str, Any] = resp.json()
        return out

    async def voice_join(self, sid: str) -> dict[str, Any]:
        out: dict[str, Any] = await self._call("POST", f"/sessions/{sid}/voice/join")
        return out

    async def end(self, sid: str) -> dict[str, Any]:
        out: dict[str, Any] = await self._call("POST", f"/sessions/{sid}/end")
        return out

    async def session(self, sid: str) -> dict[str, Any]:
        out: dict[str, Any] = await self._call("GET", f"/sessions/{sid}")
        return out

    async def debrief(self, sid: str) -> dict[str, Any]:
        """Wait until the debrief is ready or failed, then return it."""

        async def done() -> dict[str, Any] | None:
            row: dict[str, Any] = await self._call("GET", f"/sessions/{sid}/debrief")
            return row if row["status"] in ("ready", "failed", "not_ended", "not_started") else None

        result: dict[str, Any] = await self._wait("the debrief", done)
        return result
