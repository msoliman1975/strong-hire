"""Simulations: AI candidate interviews started from the admin app (docs/admin-spec.md, SM).

    GET    /admin/sim/options             the form: personas, choices, estimates, budget, gate
    GET    /admin/sim/runs                admin runs (sim_runs) and suite runs (read from disk)
    POST   /admin/sim/runs                start one: gate (409 with the reason), queue, audit
    GET    /admin/sim/runs/{id}           one admin run
    PATCH  /admin/sim/runs/{id}           {keep}: retention never deletes a kept run
    DELETE /admin/sim/runs/{id}           {reason}: the sim service deletes the folder
    POST   /admin/sim/runs/{id}/cancel    queued or waiting: cancelled now; active: the sim service
                                          ends the session within a few seconds
    GET    /admin/sessions/{id}/replay    transcript with times and response times, judge,
                                          scorecard and audio info, for the replay page

The api only writes sim_runs rows; the sim service (strong-sim serve) runs them and is the only
writer of run folders, which the api reads from SIM_RESULTS_DIR (read-only mount). Every write
needs the X-Admin-Request header and is audited (AA-5, AA-6).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.admin.actions import ActionIn, AdminWrite, audit_action
from strong_api.admin.deps import Admin, admin_settings
from strong_api.admin.router import (
    _audit,
    _content_user,
    _find,
    _transcript,
    find_session_folder,
)
from strong_api.admin.sim_schemas import (
    LATENCY_SLOW_MS,
    Channel,
    ReplayAudio,
    ReplayJudge,
    ReplayLatency,
    ReplayLine,
    ReplayProblem,
    ReplayRule,
    RunSource,
    SessionReplay,
    SimBehaviorOut,
    SimBudgetOut,
    SimCancelIn,
    SimEstimateOut,
    SimGateOut,
    SimKeepIn,
    SimOptions,
    SimPersonaOut,
    SimQueueOut,
    SimRunIn,
    SimRunList,
    SimRunOut,
    SimScenarioOut,
)
from strong_api.auth.deps import DbSession
from strong_api.auth.sim import ensure_sim_user, is_sim_user
from strong_api.billing.entitlements import as_utc
from strong_api.scoring.router import scorecard_contract
from strong_core import sim as core_sim
from strong_core.config import get_settings
from strong_core.db.models import Scorecard, SimRun, UsageEvent
from strong_core.gateway import get_gateway
from strong_core.gateway.prices import load_token_prices
from strong_core.schemas import Difficulty, InterviewType, Mode
from strong_core.schemas.enums import SimRunStatus

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

DURATIONS = (10, 30, 45)
MAX_WAITING = 5  # SM-2: one active run, up to 5 more in line
LIST_LIMIT = 200
ACTIVE = (SimRunStatus.STARTING, SimRunStatus.INTERVIEWING, SimRunStatus.JUDGING)
PENDING = (SimRunStatus.QUEUED, SimRunStatus.WAITING)
SUITE_STATUS = {
    "ok": SimRunStatus.DONE,
    "error": SimRunStatus.FAILED,
    "cancelled": SimRunStatus.CANCELLED,
}
MMSS = re.compile(r"^(\d{1,3}):([0-5]\d)$")


def _now() -> datetime:
    return datetime.now(UTC)


def _prices() -> dict[str, tuple[float, float]]:
    """alias -> (input, output) USD per million tokens, from config/litellm.<profile>.yaml."""
    settings = get_settings()
    prices = load_token_prices(settings.resolved_config_dir, str(settings.model_profile))
    return {k: (v.input_per_token * 1e6, v.output_per_token * 1e6) for k, v in prices.items()}


def _money(value: Decimal | float | None) -> float | None:
    return None if value is None else round(float(value), 4)


# --- run folders on disk (read-only here) ----------------------------------------------------


@dataclass(frozen=True)
class _Report:
    mtime: float
    summary: dict[str, Any]
    sessions: list[dict[str, Any]]


_report_cache: dict[Path, _Report] = {}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _scan_reports(results_dir: str) -> dict[str, _Report]:
    """report.json of every run folder, by folder name. Cached by mtime: the list polls."""
    root = Path(results_dir)
    if not root.is_dir():
        return {}
    out: dict[str, _Report] = {}
    for path in root.glob("*/report.json"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        cached = _report_cache.get(path)
        if cached is None or cached.mtime != mtime:
            data = _read_json(path)
            if not isinstance(data, dict):
                continue
            sessions = [s for s in data.get("sessions") or [] if isinstance(s, dict)]
            cached = _Report(mtime, data.get("summary") or {}, sessions)
            _report_cache[path] = cached
        out[path.parent.name] = cached
    return out


def _folders(results_dir: str) -> set[str]:
    root = Path(results_dir)
    return {p.name for p in root.iterdir() if p.is_dir()} if root.is_dir() else set()


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# --- shared reads ----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Queue:
    active: int
    waiting: int


async def _queue(db: AsyncSession) -> _Queue:
    rows = await db.execute(
        select(SimRun.status, func.count())
        .where(SimRun.status.in_((*ACTIVE, *PENDING)), SimRun.deleted_at.is_(None))
        .group_by(SimRun.status)
    )
    counts = {s: n for s, n in rows}
    return _Queue(
        active=sum(counts.get(s, 0) for s in ACTIVE),
        waiting=sum(counts.get(s, 0) for s in PENDING),
    )


async def _app_costs(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, float]:
    """SM-4: the app side of a run's cost, every usage row of its session."""
    if not ids:
        return {}
    rows = await db.execute(
        select(UsageEvent.session_id, func.sum(UsageEvent.cost_usd))
        .where(UsageEvent.session_id.in_(ids))
        .group_by(UsageEvent.session_id)
    )
    return {sid: round(float(cost or 0), 4) for sid, cost in rows if sid is not None}


async def _hire_signals(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await db.execute(
        select(Scorecard.session_id, Scorecard.hire_signal).where(Scorecard.session_id.in_(ids))
    )
    return {sid: str(signal) for sid, signal in rows}


def _scenario(data: dict[str, Any]) -> SimScenarioOut:
    """From a sim Scenario (scenario_json, meta.json) or a report row: both name the resume."""
    return SimScenarioOut(
        channel=str(data.get("channel") or "text"),
        interview_type=str(data.get("interview_type") or ""),
        difficulty=str(data.get("difficulty") or ""),
        mode=str(data.get("mode") or ""),
        duration_min=int(data.get("duration_min") or 0),
        persona=str(data.get("resume") or ""),
        quality=str(data.get("quality") or ""),
        behavior=str(data.get("behavior") or ""),
        candidate_name=data.get("candidate_name") or None,
    )


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _admin_out(
    run: SimRun,
    report: _Report | None,
    files: bool,
    app_cost: float | None,
    hire_signal: str | None,
) -> SimRunOut:
    row = report.sessions[0] if report and report.sessions else {}
    scenario = _scenario(run.scenario_json or {})
    sim_cost = _money(run.cost_sim_usd)
    total = None if sim_cost is None and app_cost is None else (sim_cost or 0) + (app_cost or 0)
    return SimRunOut(
        id=str(run.id),
        source="admin",
        suite=None,
        run_dir=run.run_dir,
        created_by=run.created_by,
        created_at=as_utc(run.created_at) or _now(),
        started_at=as_utc(run.started_at),
        finished_at=as_utc(run.finished_at),
        status=run.status,
        status_reason=run.status_reason,
        scenario=scenario,
        session_id=run.session_id,
        progress_s=run.progress_s or 0,
        planned_s=scenario.duration_min * 60,
        hire_signal=hire_signal or row.get("hire_signal"),
        failed_rules=list(row.get("failed_rules") or []),
        problems=int(row.get("problems") or 0),
        latency_p50_ms=row.get("latency_p50_ms"),
        cost_sim_usd=sim_cost,
        cost_app_usd=app_cost,
        cost_total_usd=None if total is None else round(total, 4),
        keep=run.keep,
        deleted_at=as_utc(run.deleted_at),
        deleted_by=run.deleted_by,
        delete_reason=run.delete_reason,
        files=files,
    )


def _suite_out(
    run_dir: str, report: _Report, row: dict[str, Any], app_costs: dict[uuid.UUID, float]
) -> SimRunOut:
    sid = _uuid(row.get("session_id"))
    scenario = _scenario(row)
    sim_cost = _money(row.get("sim_cost_usd"))
    app_cost = app_costs.get(sid) if sid else None
    total = None if sim_cost is None and app_cost is None else (sim_cost or 0) + (app_cost or 0)
    return SimRunOut(
        id=f"{run_dir}/{row.get('scenario_id') or ''}",
        source="suite",
        suite=report.summary.get("suite"),
        run_dir=run_dir,
        created_by=None,
        created_at=_when(report.summary.get("started_at"))
        or datetime.fromtimestamp(report.mtime, UTC),
        started_at=_when(report.summary.get("started_at")),
        finished_at=_when(report.summary.get("finished_at")),
        status=SUITE_STATUS.get(str(row.get("status")), SimRunStatus.FAILED),
        status_reason=row.get("error"),
        scenario=scenario,
        session_id=sid,
        progress_s=int(row.get("session_s") or 0),
        planned_s=scenario.duration_min * 60,
        hire_signal=row.get("hire_signal"),
        failed_rules=list(row.get("failed_rules") or []),
        problems=int(row.get("problems") or 0),
        latency_p50_ms=row.get("latency_p50_ms"),
        cost_sim_usd=sim_cost,
        cost_app_usd=app_cost,
        cost_total_usd=None if total is None else round(total, 4),
        keep=False,
        deleted_at=None,
        deleted_by=None,
        delete_reason=None,
        files=True,
    )


async def _one(db: AsyncSession, request: Request, run: SimRun) -> SimRunOut:
    settings = admin_settings(request)
    reports = await asyncio.to_thread(_scan_reports, settings.sim_results_dir)
    folders = await asyncio.to_thread(_folders, settings.sim_results_dir)
    ids = [run.session_id] if run.session_id else []
    app = await _app_costs(db, ids)
    signals = await _hire_signals(db, ids)
    sid = run.session_id
    return _admin_out(
        run,
        reports.get(run.run_dir) if run.run_dir else None,
        bool(run.run_dir and run.run_dir in folders),
        app.get(sid) if sid else None,
        signals.get(sid) if sid else None,
    )


async def _get_run(db: AsyncSession, run_id: uuid.UUID) -> SimRun:
    run = await db.get(SimRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return run


def _conflict(reason: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, reason)


# --- the form (SM-1) -------------------------------------------------------------------------


@router.get("/sim/options")
async def sim_options(_: Admin, db: DbSession) -> SimOptions:
    """SM-1: the choices, an estimate per length, today's sim budget and the gate now."""
    prices = _prices()
    estimates = []
    for minutes in DURATIONS:
        est = core_sim.estimate_session(minutes, prices)
        estimates.append(
            SimEstimateOut(
                duration_min=minutes,
                candidate_usd=round(est.candidate_usd, 4),
                judge_usd=round(est.judge_usd, 4),
                main_server_usd=round(est.main_server_usd, 4),
                total_usd=round(est.total_usd, 4),
            )
        )
    gateway = get_gateway()
    key = await core_sim.sim_key_budget(gateway)
    budget = None
    if key is not None and key.max_budget_usd is not None:
        budget = SimBudgetOut(
            limit_usd=key.max_budget_usd,
            spent_usd=round(key.spend_usd, 4),
            left_usd=round(max(0.0, key.max_budget_usd - key.spend_usd), 4),
            resets_at=key.resets_at,
        )
    gate = await core_sim.check_sim_gate(db, 0.0, gateway)
    queue = await _queue(db)
    return SimOptions(
        personas=[
            SimPersonaOut(id=k, label=p.label, posting=p.posting, level=p.level)
            for k, p in core_sim.PERSONAS.items()
        ],
        interview_types=list(InterviewType),
        difficulties=list(Difficulty),
        modes=list(Mode),
        durations=list(DURATIONS),
        qualities=list(core_sim.Quality),
        behaviors=[
            SimBehaviorOut(id=b, voice_only=b in core_sim.VOICE_ONLY) for b in core_sim.Behavior
        ],
        channels=["voice", "text"],
        estimates=estimates,
        budget=budget,
        gate=SimGateOut(ok=gate.ok, retry=gate.retry, reason=gate.reason),
        queue=SimQueueOut(active=queue.active, waiting=queue.waiting, max_waiting=MAX_WAITING),
    )


# --- runs (SM-2..SM-5, SM-12, SM-13) ---------------------------------------------------------


@router.post("/sim/runs", status_code=status.HTTP_201_CREATED)
async def start_run(
    body: SimRunIn, admin: AdminWrite, db: DbSession, request: Request
) -> SimRunOut:
    """SM-2, SM-3: queue one run. 409 with the reason when a gate is closed or the line is full."""
    queue = await _queue(db)
    if queue.waiting >= MAX_WAITING:
        raise _conflict(f"{queue.waiting} runs are already waiting; try again when one has started")
    need = core_sim.estimate_session(body.duration_min, _prices()).total_usd
    gate = await core_sim.check_sim_gate(db, need, get_gateway())
    if not gate.ok:
        raise _conflict(gate.reason or "AI candidate runs cannot start now")
    sim_user = await ensure_sim_user(db, admin_settings(request))
    await db.flush()
    run_id = uuid.uuid4()
    scenario = {  # a strong_sim Scenario
        "id": f"admin-{run_id.hex[:8]}",
        "channel": body.channel,
        "interview_type": body.interview_type.value,
        "difficulty": body.difficulty.value,
        "mode": body.mode.value,
        "duration_min": body.duration_min,
        "resume": body.persona,
        "quality": body.quality.value,
        "behavior": body.behavior.value,
        "candidate_name": core_sim.NAMES[run_id.int % len(core_sim.NAMES)],
    }
    run = SimRun(
        id=run_id,
        org_id=sim_user.org_id,
        scenario_json=scenario,
        status=SimRunStatus.QUEUED,
        created_by=admin.email,
    )
    db.add(run)
    audit_action(
        db,
        admin,
        "sim.run_started",
        f"sim_run:{run_id}",
        reason="start an AI candidate interview",
        org_id=sim_user.org_id,
        after=scenario,
        details={"estimate_usd": round(need, 4)},
    )
    await db.commit()
    await db.refresh(run)
    return await _one(db, request, run)


@router.get("/sim/runs")
async def list_runs(
    _: Admin,
    db: DbSession,
    request: Request,
    status_: Annotated[SimRunStatus | None, Query(alias="status")] = None,
    channel: Channel | None = None,
    source: RunSource | None = None,
) -> SimRunList:
    """SM-12: admin runs and suite runs, newest first. SM-4: poll while any is unfinished."""
    settings = admin_settings(request)
    reports = await asyncio.to_thread(_scan_reports, settings.sim_results_dir)
    folders = await asyncio.to_thread(_folders, settings.sim_results_dir)
    runs = list(
        await db.scalars(
            select(SimRun).order_by(SimRun.created_at.desc(), SimRun.id).limit(LIST_LIMIT)
        )
    )
    known = set(await db.scalars(select(SimRun.run_dir).where(SimRun.run_dir.is_not(None))))
    suite_rows = [
        (name, report, row)
        for name, report in reports.items()
        if name not in known
        for row in report.sessions
    ]
    ids = [r.session_id for r in runs if r.session_id]
    ids += [sid for _, _, row in suite_rows if (sid := _uuid(row.get("session_id")))]
    app = await _app_costs(db, ids)
    signals = await _hire_signals(db, [r.session_id for r in runs if r.session_id])
    out = [
        _admin_out(
            r,
            reports.get(r.run_dir) if r.run_dir else None,
            bool(r.run_dir and r.run_dir in folders),
            app.get(r.session_id) if r.session_id else None,
            signals.get(r.session_id) if r.session_id else None,
        )
        for r in runs
    ]
    out += [_suite_out(name, report, row, app) for name, report, row in suite_rows]
    if status_ is not None:
        out = [r for r in out if r.status == status_]
    if channel is not None:
        out = [r for r in out if r.scenario.channel == channel]
    if source is not None:
        out = [r for r in out if r.source == source]
    out.sort(key=lambda r: r.created_at, reverse=True)
    return SimRunList(
        runs=out[:LIST_LIMIT],
        any_unfinished=any(not r.status.finished for r in out if r.source == "admin"),
    )


@router.get("/sim/runs/{run_id}")
async def get_run(run_id: uuid.UUID, _: Admin, db: DbSession, request: Request) -> SimRunOut:
    return await _one(db, request, await _get_run(db, run_id))


@router.patch("/sim/runs/{run_id}")
async def keep_run(
    run_id: uuid.UUID, body: SimKeepIn, admin: AdminWrite, db: DbSession, request: Request
) -> SimRunOut:
    """SM-13: Keep, so retention never deletes the run's files."""
    run = await _get_run(db, run_id)
    if run.deleted_at is not None:
        raise _conflict("The run's files are deleted")
    before = run.keep
    run.keep = body.keep
    audit_action(
        db,
        admin,
        "sim.run_keep",
        f"sim_run:{run.id}",
        reason="keep" if body.keep else "stop keeping",
        org_id=run.org_id,
        before={"keep": before},
        after={"keep": body.keep},
    )
    await db.commit()
    return await _one(db, request, run)


@router.delete("/sim/runs/{run_id}")
async def delete_run(
    run_id: uuid.UUID, body: ActionIn, admin: AdminWrite, db: DbSession, request: Request
) -> SimRunOut:
    """SM-13: the row stays as a stub; the sim service deletes the folder within seconds."""
    run = await _get_run(db, run_id)
    if not run.status.finished:
        raise _conflict("The run is not finished; cancel it first")
    if run.deleted_at is not None:
        raise _conflict("The run is already deleted")
    run.deleted_at, run.deleted_by, run.delete_reason = _now(), admin.email, body.reason
    audit_action(
        db,
        admin,
        "sim.run_deleted",
        f"sim_run:{run.id}",
        reason=body.reason,
        org_id=run.org_id,
        details={"run_dir": run.run_dir, "keep": run.keep},
    )
    await db.commit()
    return await _one(db, request, run)


@router.post("/sim/runs/{run_id}/cancel")
async def cancel_run(
    run_id: uuid.UUID, body: SimCancelIn, admin: AdminWrite, db: DbSession, request: Request
) -> SimRunOut:
    """SM-5: a run in line is cancelled now; an active one stops within a few seconds."""
    run = await _get_run(db, run_id)
    if run.status.finished:
        raise _conflict(f"The run is already {run.status.value}")
    before = run.status
    run.cancel_requested_at = run.cancel_requested_at or _now()
    if run.status in PENDING:
        run.status, run.status_reason = SimRunStatus.CANCELLED, "cancelled before it started"
        run.finished_at = _now()
    audit_action(
        db,
        admin,
        "sim.run_cancelled",
        f"sim_run:{run.id}",
        reason=body.reason or "cancel",
        org_id=run.org_id,
        before={"status": before.value},
        after={"status": run.status.value},
    )
    await db.commit()
    return await _one(db, request, run)


# --- replay (SM-6..SM-11) --------------------------------------------------------------------


def _at_ms(at: str) -> int | None:
    found = MMSS.match(at.strip())
    return (int(found[1]) * 60 + int(found[2])) * 1000 if found else None


def _nearest_rank(values: list[int], p: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1))))]


@dataclass(frozen=True)
class _Files:
    folder: Path
    transcript: Any
    judge: Any
    meta: Any
    audio_bytes: int | None


def _read_folder(folder: Path) -> _Files:
    audio = folder / "audio.ogg"
    return _Files(
        folder=folder,
        transcript=_read_json(folder / "transcript.json"),
        judge=_read_json(folder / "judge.json"),
        meta=_read_json(folder / "meta.json"),
        audio_bytes=audio.stat().st_size if audio.is_file() else None,
    )


def _lines(raw: Any) -> list[ReplayLine]:
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or item.get("speaker") not in ("interviewer", "candidate"):
            continue
        out.append(
            ReplayLine(
                speaker=item["speaker"],
                text=str(item.get("text") or ""),
                start_ms=int(item.get("start_ms") or 0),
                end_ms=int(item.get("end_ms") or 0),
                phase=item.get("phase"),
                note=item.get("note"),
                latency_ms=item.get("latency_ms"),
            )
        )
    return out


def _judge(raw: Any) -> ReplayJudge | None:
    if not isinstance(raw, dict):
        return None
    rules = [
        ReplayRule(rule=str(r["rule"]), verdict=str(r["verdict"]), reason=str(r.get("reason", "")))
        for r in raw.get("rules") or []
        if isinstance(r, dict) and "rule" in r and "verdict" in r
    ]
    problems = [
        ReplayProblem(at=str(p["at"]), at_ms=_at_ms(str(p["at"])), problem=str(p["problem"]))
        for p in raw.get("problems") or []
        if isinstance(p, dict) and "at" in p and "problem" in p
    ]
    return ReplayJudge(
        rubric=raw.get("rubric"), model=raw.get("model"), rules=rules, problems=problems
    )


@router.get("/sessions/{session_id}/replay")
async def session_replay(
    session_id: uuid.UUID, admin: Admin, db: DbSession, request: Request
) -> SessionReplay:
    """SM-7..SM-11: everything the replay page shows. AI candidate interviews only; same
    consent rule as the transcript. Audited."""
    row, found_user, card = await _find(db, session_id)
    user = _content_user(found_user)
    if not await is_sim_user(db, user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Replay is for AI candidate interviews")
    settings = admin_settings(request)
    folder = await asyncio.to_thread(find_session_folder, settings.sim_results_dir, row.id)
    files = await asyncio.to_thread(_read_folder, folder) if folder else None
    meta = files.meta if files and isinstance(files.meta, dict) else {}

    lines = _lines(files.transcript) if files else []
    timed = bool(lines) and meta.get("timing") == "audio"
    if not lines:  # no run folder, or an empty one: the interview as the app stored it
        lines = [
            ReplayLine(
                speaker="interviewer" if t.speaker == "interviewer" else "candidate",
                text=t.text,
                start_ms=t.start_ms or 0,
                end_ms=t.end_ms or t.start_ms or 0,
                phase=str(t.phase) if t.phase else None,
                note=None,
                latency_ms=None,
            )
            for t in await _transcript(db, row)
        ]
    waits = [x.latency_ms for x in lines if x.latency_ms is not None]
    sim_run_id = await db.scalar(select(SimRun.id).where(SimRun.session_id == row.id).limit(1))
    scenario = meta.get("scenario")
    db.add(
        _audit(admin, "admin.replay_viewed", row, {"user_id": str(user.id), "lines": len(lines)})
    )
    await db.commit()
    return SessionReplay(
        session_id=row.id,
        run_dir=files.folder.parent.name if files else None,
        sim_run_id=sim_run_id,
        channel=str(row.channel),
        timing="audio" if timed else "approximate",
        lines=lines,
        latency=ReplayLatency(
            n=len(waits),
            p50_ms=_nearest_rank(waits, 50),
            p90_ms=_nearest_rank(waits, 90),
            slow_turns=sum(1 for w in waits if w > LATENCY_SLOW_MS),
        ),
        judge=_judge(files.judge) if files else None,
        scorecard=scorecard_contract(card) if card is not None else None,
        audio=ReplayAudio(
            available=bool(files and files.audio_bytes is not None),
            bytes=files.audio_bytes if files else None,
        ),
        scenario=_scenario(scenario) if isinstance(scenario, dict) else None,
    )
