"""Run a suite: each scenario becomes one session, judged, saved and uploaded (P13)."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from strong_core.gateway import ModelGateway, Role
from strong_sim.candidate import Candidate, Pacer
from strong_sim.client import AppClient
from strong_sim.cost import CostLimitError, CostMeter
from strong_sim.judge import judge
from strong_sim.report import SessionRow, percentile, render_html, summary
from strong_sim.scenarios import Scenario, Suite
from strong_sim.sessions import Conversation, run_text, run_voice
from strong_sim.settings import SimSettings
from strong_sim.store import Uploader, save_session, write_json

log = logging.getLogger("strong_sim")


def new_run_id(suite: str) -> str:
    return f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{suite}-{uuid.uuid4().hex[:4]}"


async def run_scenario(
    scenario: Scenario,
    client: AppClient,
    gateway: ModelGateway,
    settings: SimSettings,
    meter: CostMeter,
    run_dir: Path,
    pacer: Pacer | None = None,
) -> SessionRow:
    row = SessionRow(
        scenario_id=scenario.id,
        channel=scenario.channel,
        interview_type=scenario.interview_type.value,
        difficulty=scenario.difficulty.value,
        mode=scenario.mode.value,
        duration_min=scenario.duration_min,
        resume=scenario.resume,
        quality=scenario.quality.value,
        behavior=scenario.behavior.value,
        status="ok",
    )
    before = meter.total_usd
    started = time.perf_counter()
    folder: Path | None = None
    conv = Conversation()
    try:
        job_id = await client.job_for(scenario)
        record = await client.create_session(scenario, job_id)
        sid = row.session_id = record["id"]
        folder = run_dir / sid
        folder.mkdir(parents=True, exist_ok=True)
        log.info("%s: session %s (%s)", scenario.id, sid, scenario.channel)
        candidate = Candidate(scenario, gateway, meter, pacer or Pacer())
        if scenario.channel == "voice":
            conv = await run_voice(
                scenario, client, candidate, sid, settings, gateway, folder / "audio.ogg"
            )
        else:
            conv = await run_text(scenario, client, candidate, sid, settings)
        row.session_s = time.perf_counter() - started
        row.ended_by_server, row.stopped_early = conv.ended_by_server, conv.stopped_early
        row.candidate_turns = sum(1 for line in conv.lines if line.speaker == "candidate")
        row.latency_p50_ms = percentile(conv.turn_latency_ms, 50)
        row.latency_p95_ms = percentile(conv.turn_latency_ms, 95)
        row.has_audio = bool(conv.audio_path and conv.audio_path.exists())
        verdict = await judge(
            scenario, conv.lines, gateway, meter, stopped_early=conv.stopped_early
        )
        row.rules = {r.rule: r.verdict for r in verdict.rules}
        row.failed_rules, row.problems = verdict.failed, len(verdict.problems)
        debrief = await client.debrief(sid)
        row.debrief_status = debrief.get("status")
        scorecard = debrief.get("scorecard") or {}
        row.hire_signal = scorecard.get("hire_signal")
        row.sim_cost_usd = meter.total_usd - before
        save_session(
            folder,
            conv.lines,
            {
                "judge.json": verdict.model_dump(),
                "debrief.json": debrief,
                "meta.json": {
                    "scenario": scenario.model_dump(mode="json"),
                    "session": await client.session(sid),
                    "candidate_model": gateway.config.alias_for(Role.CANDIDATE),
                    "judge_model": gateway.config.alias_for(Role.JUDGE),
                    "prompts": [*candidate.prompt_refs, verdict.rubric],
                    "notes": conv.notes,
                    "turn_latency_ms": conv.turn_latency_ms,
                    "sim_cost_usd": row.sim_cost_usd,
                    "row": row.model_dump(),
                },
            },
        )
    except CostLimitError:
        raise
    except Exception as exc:  # one broken session must not stop the run
        log.exception("%s failed", scenario.id)
        row.status, row.error = "error", f"{type(exc).__name__}: {exc}"[:500]
        if row.session_id:  # do not leave the session open on the server
            try:
                await client.end(row.session_id)
            except Exception:
                log.warning("could not end session %s", row.session_id)
        row.session_s = time.perf_counter() - started
        row.sim_cost_usd = meter.total_usd - before
        if folder is not None:
            save_session(folder, conv.lines, {"meta.json": {"error": row.error,
                                                            "row": row.model_dump()}})  # fmt: skip
    return row


def write_report(run_dir: Path, rows: list[SessionRow], meta: dict[str, Any]) -> dict[str, Any]:
    info = summary(rows, meta)
    write_json(
        run_dir / "report.json", {"summary": info, "sessions": [r.model_dump() for r in rows]}
    )
    (run_dir / "report.html").write_text(render_html(rows, info), encoding="utf-8")
    return info


async def run_suite(
    suite: Suite,
    settings: SimSettings,
    gateway: ModelGateway,
    meter: CostMeter,
    run_id: str | None = None,
    client: AppClient | None = None,
) -> tuple[Path, dict[str, Any]]:
    run_id = run_id or new_run_id(suite.name)
    run_dir = settings.out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "scenarios.yaml").write_text(
        yaml.safe_dump(
            {"name": suite.name, "scenarios": [s.model_dump(mode="json") for s in suite.scenarios]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    uploader = Uploader(settings)
    client = client or AppClient(settings)
    meta: dict[str, Any] = {
        "run_id": run_id,
        "suite": suite.name,
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "base_url": settings.base_url,
        "candidate_model": gateway.config.alias_for(Role.CANDIDATE),
        "judge_model": gateway.config.alias_for(Role.JUDGE),
    }
    rows: list[SessionRow] = []
    pacer = Pacer(min_interval_s=settings.candidate_min_interval_s)
    try:
        me = await client.sign_in()
        meta["sim_user"] = (me.get("user") or {}).get("email")
        for scenario in suite.scenarios:
            row = await run_scenario(scenario, client, gateway, settings, meter, run_dir, pacer)
            rows.append(row)
            log.info(
                "%s: %s, failed rules %s, signal %s, $%.3f",
                scenario.id, row.status, row.failed_rules or "none", row.hire_signal,
                row.sim_cost_usd,
            )  # fmt: skip
            write_report(run_dir, rows, meta)
            if not uploader.push(run_dir):
                log.error("upload failed after %s; files stay in %s", scenario.id, run_dir)
    except CostLimitError as exc:
        log.error("%s; stopping the run", exc)
        meta["stopped"] = str(exc)
    finally:
        meta["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        info = write_report(run_dir, rows, meta)
        uploader.push(run_dir)
        await client.aclose()
    return run_dir, info
