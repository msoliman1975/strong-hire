"""strong-sim serve: the sim service on the main server (docs/admin-spec.md, Simulations).

One loop, one run at a time (D-13):
- the oldest queued or waiting sim_runs row runs next: the start gate (SM-3), then one session,
  with its status and progress in the row (SM-4) and cancel within a few seconds (SM-5);
- the files of runs an admin deleted go (SM-13), and once an hour retention runs (SM-14).

The admin app only writes rows; this service is the only one that writes run folders. The
interview goes through the public URL like a browser. Model calls go through the main LiteLLM
with the sim key, which enforces the daily budget for both sides, so nothing is reported to
POST /auth/sim-spend (that would count the cost twice).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strong_core.db.models import SimRun
from strong_core.gateway import ModelGateway, Role
from strong_core.schemas.enums import SimRunStatus
from strong_core.sim import NAMES, check_sim_gate
from strong_sim import retention
from strong_sim.candidate import Pacer
from strong_sim.client import AppClient
from strong_sim.cost import CostMeter, estimate, load_prices
from strong_sim.report import SessionRow
from strong_sim.runner import RunHooks, new_run_id, run_scenario, write_report
from strong_sim.scenarios import Scenario
from strong_sim.settings import SimSettings

log = logging.getLogger("strong_sim.serve")

ACTIVE = (SimRunStatus.STARTING, SimRunStatus.INTERVIEWING, SimRunStatus.JUDGING)
PENDING = (SimRunStatus.QUEUED, SimRunStatus.WAITING)
DELETE_SWEEP_DAYS = 7  # files of runs deleted in this window are checked again

ClientFactory = Callable[[SimSettings], AppClient]


def _now() -> datetime:
    return datetime.now(UTC)


def forget_pasted(scenario: dict[str, Any]) -> dict[str, Any]:
    """SM-20: a deleted run keeps that a job or CV was pasted, not the texts. The admin api does
    the same on Delete (strong_api.admin.sim.forget_pasted)."""
    gone = [k for k in ("job", "cv") if str(scenario.get(f"{k}_text") or "").strip()]
    if not gone:
        return scenario
    return {**scenario, "job_text": "", "cv_text": "", "pasted_deleted": gone}


def _start_folder(run_dir: Path, scenario: Scenario) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    # SM-19: the pasted texts as given, next to the run's sessions.
    for name, text in (("job.txt", scenario.job_text), ("cv.txt", scenario.cv_text)):
        if text.strip():
            (run_dir / name).write_text(text.strip() + "\n", encoding="utf-8")
    (run_dir / "scenarios.yaml").write_text(
        yaml.safe_dump(
            {"name": "admin", "scenarios": [scenario.model_dump(mode="json")]}, sort_keys=False
        ),
        encoding="utf-8",
    )


class SimService:
    def __init__(
        self,
        settings: SimSettings,
        sessionmaker: async_sessionmaker[AsyncSession],
        gateway: ModelGateway,
        client_factory: ClientFactory = AppClient,
    ) -> None:
        self.settings = settings
        self.sessionmaker = sessionmaker
        self.gateway = gateway
        self.client_factory = client_factory
        self.prices = load_prices()
        self.base = settings.out_dir
        self._waiting_since: dict[uuid.UUID, float] = {}
        self._check_after: dict[uuid.UUID, float] = {}
        self._last_retention = 0.0

    # ------------------------------------------------------------------ loop

    async def serve(self) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        await self.recover()
        log.info("sim service ready; runs folder %s", self.base)
        while True:
            try:
                worked = await self.tick()
            except Exception:
                log.exception("sim service loop failed; trying again")
                worked = False
            if not worked:
                await asyncio.sleep(self.settings.poll_s)

    async def tick(self) -> bool:
        """One pass: housekeeping, then at most one run. True when a run was handled."""
        await self.sweep_deleted()
        if time.monotonic() - self._last_retention >= self.settings.retention_every_s:
            await self.apply_retention()
            self._last_retention = time.monotonic()
        run_id = await self._next_run()
        if run_id is None:
            return False
        await self.process(run_id)
        return True

    async def recover(self) -> None:
        """Runs left active by a restart cannot go on: their session and audio are gone."""
        async with self.sessionmaker() as db:
            rows = (await db.scalars(select(SimRun).where(SimRun.status.in_(ACTIVE)))).all()
            for run in rows:
                self._finish(run, SimRunStatus.FAILED, "the sim service restarted during the run")
            await db.commit()

    async def _next_run(self) -> uuid.UUID | None:
        async with self.sessionmaker() as db:
            run = await db.scalar(
                select(SimRun)
                .where(SimRun.status.in_(PENDING), SimRun.deleted_at.is_(None))
                .order_by(SimRun.created_at, SimRun.id)
                .limit(1)
            )
        if run is None:
            return None
        if self._check_after.get(run.id, 0.0) > time.monotonic():
            return None  # the first run in line is waiting (SM-3); the rest wait behind it
        return run.id

    # ------------------------------------------------------------------ one run

    async def process(self, run_id: uuid.UUID) -> None:
        async with self.sessionmaker() as db:
            run = await db.get(SimRun, run_id)
            if run is None or run.status not in PENDING:
                return
            if run.cancel_requested_at is not None:
                self._finish(run, SimRunStatus.CANCELLED, "cancelled before it started")
                await db.commit()
                return
            try:
                scenario = Scenario.model_validate(run.scenario_json)
            except ValueError as exc:
                self._finish(run, SimRunStatus.FAILED, f"invalid scenario: {exc}"[:500])
                await db.commit()
                return
            if not scenario.candidate_name:
                scenario.candidate_name = NAMES[run_id.int % len(NAMES)]
            need = estimate([scenario.duration_min], self.prices)["total_usd"]
            gate = await check_sim_gate(db, need, self.gateway)
            if not gate.ok:
                await self._blocked(db, run, gate.retry, gate.reason or "not allowed now")
                return
            self._waiting_since.pop(run_id, None)
            self._check_after.pop(run_id, None)
            run.status, run.status_reason = SimRunStatus.STARTING, None
            run.started_at = _now()
            run.run_dir = new_run_id("admin")
            await db.commit()
            run_dir = self.base / run.run_dir
        await self._run(run_id, scenario, run_dir)

    async def _blocked(self, db: AsyncSession, run: SimRun, retry: bool, reason: str) -> None:
        if not retry:
            self._finish(run, SimRunStatus.FAILED, reason)
        else:
            since = self._waiting_since.setdefault(run.id, time.monotonic())
            if time.monotonic() - since >= self.settings.wait_limit_s:
                minutes = round(self.settings.wait_limit_s / 60)
                self._finish(run, SimRunStatus.FAILED, f"waited {minutes} min: {reason}")
                self._waiting_since.pop(run.id, None)
            else:
                run.status, run.status_reason = SimRunStatus.WAITING, reason
                self._check_after[run.id] = time.monotonic() + self.settings.wait_recheck_s
        await db.commit()

    async def _run(self, run_id: uuid.UUID, scenario: Scenario, run_dir: Path) -> None:
        await asyncio.to_thread(_start_folder, run_dir, scenario)
        meter = CostMeter(self.prices, limit_usd=self.settings.cost_limit_usd)
        client = self.client_factory(self.settings)
        interview_started: list[float] = []

        async def on_session(sid: str) -> None:
            interview_started.append(time.monotonic())
            await self._update(run_id, status=SimRunStatus.INTERVIEWING, session_id=uuid.UUID(sid))

        async def on_judging() -> None:
            await self._update(run_id, status=SimRunStatus.JUDGING)

        async def session() -> SessionRow:
            await client.sign_in()
            return await run_scenario(
                scenario, client, self.gateway, self.settings, meter, run_dir,
                Pacer(min_interval_s=self.settings.candidate_min_interval_s),
                RunHooks(on_session=on_session, on_judging=on_judging),
            )  # fmt: skip

        meta: dict[str, Any] = {
            "run_id": run_dir.name,
            "suite": "admin",
            "started_at": _now().isoformat(timespec="seconds"),
            "base_url": self.settings.base_url,
            "candidate_model": self.gateway.config.alias_for(Role.CANDIDATE),
            "judge_model": self.gateway.config.alias_for(Role.JUDGE),
        }
        task = asyncio.create_task(session())
        cancelled = False
        last_progress = 0.0
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=min(2.0, self.settings.poll_s))
                if task.done():
                    break
                if not cancelled and await self._cancel_requested(run_id):
                    log.info("run %s: cancel requested", run_id)
                    task.cancel()
                    cancelled = True
                now = time.monotonic()
                if interview_started and now - last_progress >= self.settings.progress_every_s:
                    last_progress = now
                    await self._update(run_id, progress_s=int(now - interview_started[0]))
            row: SessionRow | None = task.result()
            ok = row is not None and row.status == "ok"
            status = SimRunStatus.DONE if ok else SimRunStatus.FAILED
            reason = None if ok else (row.error if row else None) or "the session failed"
        except asyncio.CancelledError:
            if not cancelled:
                task.cancel()
                raise  # the service itself is stopping
            row, status, reason = None, SimRunStatus.CANCELLED, "cancelled by an admin"
        except Exception as exc:  # sign-in and other failures outside the session
            log.exception("run %s failed", run_id)
            row, status = None, SimRunStatus.FAILED
            reason = f"{type(exc).__name__}: {exc}"[:500]
        finally:
            with contextlib.suppress(Exception):
                await client.aclose()
        meta["finished_at"] = _now().isoformat(timespec="seconds")
        if row is not None:
            write_report(run_dir, [row], meta)
        progress = int(time.monotonic() - interview_started[0]) if interview_started else 0
        async with self.sessionmaker() as db:
            run = await db.get(SimRun, run_id)
            if run is not None:
                run.cost_sim_usd = Decimal(str(round(meter.total_usd, 4)))
                run.progress_s = progress
                self._finish(run, status, reason)
                await db.commit()
        log.info("run %s: %s, sim-side $%.3f", run_id, status.value, meter.total_usd)

    async def _cancel_requested(self, run_id: uuid.UUID) -> bool:
        async with self.sessionmaker() as db:
            at = await db.scalar(select(SimRun.cancel_requested_at).where(SimRun.id == run_id))
        return at is not None

    async def _update(self, run_id: uuid.UUID, **values: Any) -> None:
        async with self.sessionmaker() as db:
            run = await db.get(SimRun, run_id)
            if run is None:
                return
            for key, value in values.items():
                setattr(run, key, value)
            await db.commit()

    @staticmethod
    def _finish(run: SimRun, status: SimRunStatus, reason: str | None) -> None:
        run.status, run.status_reason = status, reason
        run.finished_at = _now()

    # ------------------------------------------------------------------ files

    async def sweep_deleted(self) -> None:
        """SM-13: the api marks a run deleted; its folder goes here."""
        since = _now() - timedelta(days=DELETE_SWEEP_DAYS)
        async with self.sessionmaker() as db:
            names = (
                await db.scalars(
                    select(SimRun.run_dir).where(
                        SimRun.deleted_at.is_not(None),
                        SimRun.deleted_at >= since,
                        SimRun.run_dir.is_not(None),
                    )
                )
            ).all()
        for name in names:
            if name and (self.base / name).exists():
                await asyncio.to_thread(retention.delete_folder, self.base, name)
                log.info("deleted the files of run folder %s (admin)", name)

    async def apply_retention(self) -> list[str]:
        """SM-14: delete what retention.plan() says and record it on the runs' rows."""
        folders = await asyncio.to_thread(retention.scan, self.base)
        async with self.sessionmaker() as db:
            rows = (await db.scalars(select(SimRun).where(SimRun.run_dir.is_not(None)))).all()
            protected = {
                r.run_dir for r in rows
                if r.run_dir and (r.keep or r.status in ACTIVE or r.status in PENDING)
            }  # fmt: skip
            doomed = retention.plan(
                folders, protected, _now(), self.settings.keep_days, self.settings.keep_gb
            )
            by_dir = {r.run_dir: r for r in rows}
            for name, reason in doomed:
                await asyncio.to_thread(retention.delete_folder, self.base, name)
                log.info("retention deleted %s: %s", name, reason)
                run = by_dir.get(name)
                if run is not None and run.deleted_at is None:
                    run.deleted_at, run.deleted_by = _now(), "retention"
                    run.delete_reason = reason
                    run.scenario_json = forget_pasted(run.scenario_json)
            await db.commit()
        return [name for name, _ in doomed]
