"""The run report: report.json and a self-contained report.html (P13)."""

from __future__ import annotations

import html
import itertools
import statistics
from typing import Any

from pydantic import BaseModel, Field

from strong_sim.judge import RULES

# FB-1 order, strongest first. Lower rank = stronger signal.
SIGNAL_RANK = {"Strong Hire": 0, "Hire": 1, "Lean Hire": 2, "Lean No Hire": 3, "No Hire": 4}
QUALITY_RANK = {"strong": 0, "average": 1, "weak": 2}


class SessionRow(BaseModel):
    scenario_id: str
    session_id: str | None = None
    channel: str
    interview_type: str
    difficulty: str
    mode: str
    duration_min: int
    resume: str
    quality: str
    behavior: str
    status: str = Field(description="ok, or error")
    error: str | None = None
    ended_by_server: bool = False
    stopped_early: bool = False
    rules: dict[str, str] = Field(default_factory=dict, description="rule -> verdict")
    failed_rules: list[str] = Field(default_factory=list)
    problems: int = 0
    hire_signal: str | None = None
    debrief_status: str | None = None
    session_s: float = 0.0
    candidate_turns: int = 0
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    sim_cost_usd: float = 0.0
    has_audio: bool = False


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1))))
    return ordered[k]


def order_breaks(rows: list[SessionRow]) -> list[str]:
    """Scorer check: with everything else equal, strong >= average >= weak in hire signal."""

    def key(r: SessionRow) -> tuple[str, ...]:
        return (r.channel, r.interview_type, r.difficulty, r.mode, str(r.duration_min), r.resume,
                r.behavior)  # fmt: skip

    breaks = []
    scored = sorted((r for r in rows if r.hire_signal in SIGNAL_RANK), key=key)
    for _, group in itertools.groupby(scored, key=key):
        members = list(group)
        for a, b in itertools.combinations(members, 2):
            qa, qb = QUALITY_RANK[a.quality], QUALITY_RANK[b.quality]
            if qa == qb:
                continue
            stronger, weaker = (a, b) if qa < qb else (b, a)
            assert stronger.hire_signal and weaker.hire_signal
            if SIGNAL_RANK[stronger.hire_signal] > SIGNAL_RANK[weaker.hire_signal]:
                breaks.append(
                    f"{stronger.scenario_id} ({stronger.quality}) got {stronger.hire_signal}, "
                    f"below {weaker.scenario_id} ({weaker.quality}) with {weaker.hire_signal}"
                )
    return breaks


def summary(rows: list[SessionRow], meta: dict[str, Any]) -> dict[str, Any]:
    ok = [r for r in rows if r.status == "ok"]
    judged = [r for r in ok if r.rules]
    per_rule = {
        rule: {
            v: sum(1 for r in judged if r.rules.get(rule) == v)
            for v in ("pass", "fail", "not_applicable")
        }
        for rule in RULES
    }
    lat = [x for r in ok for x in ([r.latency_p50_ms] if r.latency_p50_ms else [])]
    return {
        **meta,
        "sessions": len(rows),
        "sessions_ok": len(ok),
        "sessions_error": len(rows) - len(ok),
        "sessions_all_rules_pass": sum(1 for r in judged if not r.failed_rules),
        "per_rule": per_rule,
        "order_breaks": order_breaks(ok),
        "median_turn_latency_ms": statistics.median(lat) if lat else None,
        "sim_cost_usd": round(sum(r.sim_cost_usd for r in rows), 4),
    }


_CSS = """
:root{--bg:#fff;--fg:#1d2330;--muted:#5b6475;--line:#d9dde5;--ok:#1b7a3d;--bad:#b42318;--na:#8a93a3}
@media (prefers-color-scheme: dark){:root{--bg:#14171d;--fg:#e6e9ef;--muted:#9aa3b2;
--line:#2c323d;--ok:#5cc98a;--bad:#ff8a80;--na:#7d8696}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:24px 16px}
h1{font-size:20px;margin:0 0 4px} .muted{color:var(--muted)} table{border-collapse:collapse;
width:100%;margin:16px 0} th,td{border-bottom:1px solid var(--line);padding:6px 8px;
text-align:left;vertical-align:top} th{font-weight:600} .pass{color:var(--ok)}
.fail{color:var(--bad);font-weight:600} .not_applicable{color:var(--na)}
.wrap{overflow-x:auto} a{color:inherit}
"""


def _cell(verdict: str | None) -> str:
    mark = {"pass": "pass", "fail": "FAIL", "not_applicable": "n/a"}.get(verdict or "", "-")
    return f'<td class="{html.escape(verdict or "")}">{mark}</td>'


def render_html(rows: list[SessionRow], info: dict[str, Any]) -> str:
    e = html.escape
    head = "".join(f"<th>{e(r)}</th>" for r in RULES)
    body = []
    for r in rows:
        link = (
            f'<a href="{e(r.session_id)}/transcript.txt">{e(r.scenario_id)}</a>'
            if r.session_id
            else e(r.scenario_id)
        )
        sid = e(r.session_id or "")
        audio = f' · <a href="{sid}/audio.ogg">audio</a>' if r.has_audio else ""
        setup = (
            f"{r.channel} · {r.interview_type} · {r.difficulty} · {r.mode} · {r.duration_min} min"
        )
        who = f"{r.resume} · {r.quality} · {r.behavior}"
        if r.status != "ok":
            body.append(
                f"<tr><td>{link}</td><td>{e(setup)}<br><span class=muted>{e(who)}</span></td>"
                f'<td colspan="{len(RULES) + 3}" class="fail">error: {e(r.error or "")}</td></tr>'
            )
            continue
        lat = f"{r.latency_p50_ms:.0f} / {r.latency_p95_ms:.0f}" if r.latency_p50_ms else "-"
        body.append(
            f"<tr><td>{link}{audio}</td><td>{e(setup)}<br><span class=muted>{e(who)}</span></td>"
            + "".join(_cell(r.rules.get(rule)) for rule in RULES)
            + f"<td>{e(r.hire_signal or r.debrief_status or '-')}</td>"
            f"<td>{r.session_s / 60:.1f} min, {r.candidate_turns} turns<br>"
            f"<span class=muted>p50/p95 {lat} ms</span></td><td>${r.sim_cost_usd:.3f}</td></tr>"
        )
    breaks = info.get("order_breaks") or []
    breaks_html = (
        "<ul>" + "".join(f"<li class=fail>{e(b)}</li>" for b in breaks) + "</ul>"
        if breaks
        else '<p class="pass">No ordering breaks among comparable scenarios.</p>'
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sim run {e(info.get("run_id", ""))}</title><style>{_CSS}</style></head><body>
<h1>Sim run {e(info.get("run_id", ""))}</h1>
<p class="muted">Suite {e(str(info.get("suite")))} · {e(str(info.get("started_at")))} ·
{info.get("sessions")} sessions ({info.get("sessions_error")} errors) ·
{info.get("sessions_all_rules_pass")} passed every rule · sim-side model cost
${info.get("sim_cost_usd", 0):.2f} · candidate {e(str(info.get("candidate_model")))} ·
judge {e(str(info.get("judge_model")))} · target {e(str(info.get("base_url")))}</p>
<h2>Scorer order check</h2>{breaks_html}
<h2>Sessions</h2><div class="wrap"><table><tr><th>Scenario</th><th>Setup</th>{head}
<th>Hire signal</th><th>Length</th><th>Sim cost</th></tr>{"".join(body)}</table></div>
</body></html>
"""
