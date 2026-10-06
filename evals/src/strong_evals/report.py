"""HTML and JSON reports for an eval run, written to evals/reports/."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from strong_evals.runner import MetricResult, RunReport

CSS = """
:root { --bg:#ffffff; --fg:#1d232b; --muted:#5b6672; --line:#d9dee4; --head:#f3f5f7;
  --pass:#1f7a3d; --pass-bg:#e3f4e8; --fail:#a8261d; --fail-bg:#fbe5e3; --info:#4a5561;
  --info-bg:#eceff2; --warn-bg:#fff4d6; --warn:#7a5600; }
@media (prefers-color-scheme: dark) { :root { --bg:#14181d; --fg:#e4e8ec; --muted:#9aa5b1;
  --line:#2c333b; --head:#1c2228; --pass:#7fd49a; --pass-bg:#173622; --fail:#f2958c;
  --fail-bg:#3d1a17; --info:#b8c2cc; --info-bg:#252c33; --warn-bg:#3a2f12; --warn:#f0cf7a; } }
body { background:var(--bg); color:var(--fg); font:14px/1.5 system-ui, sans-serif;
  margin:0 auto; max-width:1200px; padding:24px 16px; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:17px; margin:28px 0 8px; }
.muted { color:var(--muted); }
.banner { background:var(--warn-bg); color:var(--warn); padding:10px 14px; border-radius:6px;
  margin:12px 0; }
.scroll { overflow-x:auto; }
table { border-collapse:collapse; width:100%; }
th, td { border-bottom:1px solid var(--line); padding:6px 8px; text-align:left;
  vertical-align:top; }
th { background:var(--head); font-weight:600; }
.badge { display:inline-block; padding:1px 8px; border-radius:10px; font-weight:600;
  font-size:12px; }
.PASS { color:var(--pass); background:var(--pass-bg); }
.FAIL { color:var(--fail); background:var(--fail-bg); }
.INFO { color:var(--info); background:var(--info-bg); }
details { margin:4px 0; } summary { cursor:pointer; }
.turn { margin:2px 0; } .who { font-weight:600; }
"""


def _badge(passed: bool | None) -> str:
    label = {True: "PASS", False: "FAIL", None: "INFO"}[passed]
    return f'<span class="badge {label}">{label}</span>'


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f'<div class="scroll"><table><tr>{head}</tr>{body}</table></div>'


def _metric_row(m: MetricResult) -> list[str]:
    return [
        escape(m.name),
        escape(m.display),
        escape(m.threshold or "none"),
        _badge(m.passed),
        escape(m.detail),
        f'<span class="muted">{escape(m.source)}</span>',
    ]


def _turn_html(t: dict[str, Any]) -> str:
    where = escape(t["phase"]) + (" " + escape(t["question_ref"]) if t.get("question_ref") else "")
    return (
        f"<div class='turn'><span class='who'>{escape(t['speaker'])}</span> "
        f"<span class='muted'>[{where}]</span> {escape(t['text'])}</div>"
    )


def render_html(r: RunReport) -> str:
    e = escape
    verdict = "All gated metrics pass." if not r.failed else f"{len(r.failed)} metric(s) fail."
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>Eval {e(r.suite.name)} on {e(r.profile)}</title><style>{CSS}</style></head><body>",
        f"<h1>Strong Hire eval: {e(r.suite.name)} on profile {e(r.profile)}</h1>",
        f"<p class='muted'>{e(r.suite.description)}</p>",
    ]
    if r.profile == "fake":
        parts.append(
            "<div class='banner'>Fake profile: every model reply is a recorded fixture. The "
            "numbers show that the harness runs end to end. They say nothing about model "
            "quality. Run with the local or hosted profile to judge the interviewer and scorer."
            "</div>"
        )
    parts.append(f"<p><strong>{e(verdict)}</strong> Errors: {r.errors}. Scorer: {e(r.scorer)}.</p>")
    parts.append("<h2>Metrics</h2>")
    parts.append(
        _table(
            ["Metric", "Value", "Threshold", "Result", "Detail", "Threshold source"],
            [_metric_row(m) for m in r.metrics],
        )
    )

    if r.scripted:
        parts.append("<h2>Scripted transcripts (gold set)</h2>")
        rows = []
        for s in r.scripted:
            t, sess = s.transcript, s.transcript.session
            within = (
                "yes" if s.human and s.scorer and abs(s.human.rank - s.scorer.rank) <= 1 else "no"
            )
            rows.append(
                [
                    e(t.id),
                    e(sess.interview_type.value),
                    e(sess.level.value),
                    e(t.quality.value),
                    e(s.human.value if s.human else "no label"),
                    e(s.scorer.value if s.scorer else "none"),
                    within if s.human else "",
                    f"{s.rubric.within_one}/{s.rubric.n}",
                    f"{s.follow_ups.probed}/{s.follow_ups.eligible}",
                    f"{s.coverage:.0%}",
                    f"${s.cost_usd:.4f}",
                    e(s.error or ""),
                ]
            )
        parts.append(
            _table(
                [
                    "Id",
                    "Type",
                    "Level",
                    "Quality",
                    "Human signal",
                    "Scorer signal",
                    "Within one band",
                    "Rubric within one",
                    "Vague probed",
                    "Coverage",
                    "Scorer cost",
                    "Error",
                ],
                rows,
            )
        )

    if r.simulated:
        parts.append("<h2>Simulated sessions</h2>")
        rows = []
        for m in r.simulated:
            sp = m.spec
            rows.append(
                [
                    e(sp.id),
                    e(sp.candidate_name),
                    e(sp.quality.value),
                    e(sp.session.interview_type.value),
                    e(sp.session.level.value),
                    e(sp.session.difficulty.value),
                    str(len(m.turns)),
                    str(m.questions_asked),
                    f"{m.follow_ups.probed}/{m.follow_ups.eligible}",
                    f"{m.coverage:.0%}",
                    f"${m.cost_usd:.4f}",
                    e(m.scorer.value if m.scorer else "none"),
                    e(m.error or ""),
                ]
            )
        parts.append(
            _table(
                [
                    "Id",
                    "Candidate",
                    "Quality",
                    "Type",
                    "Level",
                    "Difficulty",
                    "Turns",
                    "Questions",
                    "Vague probed",
                    "Coverage",
                    "Cost",
                    "Scorer signal",
                    "Error",
                ],
                rows,
            )
        )
        for m in r.simulated:
            if not m.turns:
                continue
            lines = "".join(_turn_html(t) for t in m.turns)
            parts.append(f"<details><summary>Transcript {e(m.spec.id)}</summary>{lines}</details>")

    if r.gap:
        parts.append("<h2>Gap analysis</h2>")
        rows = [
            [
                e(g.spec.id),
                e(g.spec.posting),
                e(g.spec.resume),
                e(g.spec.fit),
                "generic" if g.generic_mode else "company",
                e(", ".join(str(s) for s in g.scores)),
                "" if g.spread is None else str(g.spread),
                e(", ".join(f"{s:.1f}" for s in g.seconds)),
                f"${g.cost_usd:.4f}",
                e(g.error or ""),
            ]
            for g in r.gap
        ]
        parts.append(
            _table(
                [
                    "Id",
                    "Posting",
                    "Resume",
                    "Fit",
                    "Mode",
                    "Match scores",
                    "Spread",
                    "Seconds",
                    "Cost",
                    "Error",
                ],
                rows,
            )
        )

    parts.append("<h2>Run details</h2>")
    parts.append(
        _table(
            ["Item", "Value"],
            [
                ["Started (UTC)", e(r.started_at)],
                ["Duration", f"{r.duration_s} s"],
                ["Git commit", e(r.git_sha)],
                ["Model aliases by role", e(", ".join(f"{k}: {v}" for k, v in r.models.items()))],
                ["Prompt versions", e(", ".join(r.prompt_refs) or "none")],
                ["Fixtures recorded", str(r.recorded)],
            ],
        )
    )
    parts.append("</body></html>")
    return "\n".join(parts)


def report_data(r: RunReport) -> dict[str, Any]:
    return {
        "suite": r.suite.name,
        "profile": r.profile,
        "started_at": r.started_at,
        "duration_s": r.duration_s,
        "git_sha": r.git_sha,
        "models": r.models,
        "prompt_refs": r.prompt_refs,
        "errors": r.errors,
        "recorded": r.recorded,
        "scorer": r.scorer,
        "metrics": [
            {
                "key": m.key,
                "name": m.name,
                "value": m.value,
                "threshold": m.threshold,
                "passed": m.passed,
                "detail": m.detail,
                "source": m.source,
            }
            for m in r.metrics
        ],
        "scripted": [
            {
                "id": s.transcript.id,
                "human": s.human,
                "scorer": s.scorer,
                "rubric_within_one": s.rubric.within_one,
                "rubric_n": s.rubric.n,
                "vague_probed": s.follow_ups.probed,
                "vague_eligible": s.follow_ups.eligible,
                "coverage": s.coverage,
                "cost_usd": str(s.cost_usd),
                "scorer_s": s.scorer_s,
                "error": s.error,
            }
            for s in r.scripted
        ],
        "simulated": [
            {
                "id": m.spec.id,
                "scorer": m.scorer,
                "turns": m.turns,
                "questions_asked": m.questions_asked,
                "vague_probed": m.follow_ups.probed,
                "vague_eligible": m.follow_ups.eligible,
                "coverage": m.coverage,
                "cost_usd": str(m.cost_usd),
                "error": m.error,
            }
            for m in r.simulated
        ],
        "gap": [
            {
                "id": g.spec.id,
                "posting": g.spec.posting,
                "resume": g.spec.resume,
                "fit": g.spec.fit,
                "generic_mode": g.generic_mode,
                "scores": g.scores,
                "spread": g.spread,
                "seconds": g.seconds,
                "cost_usd": str(g.cost_usd),
                "error": g.error,
            }
            for g in r.gap
        ],
    }


def write_report(r: RunReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = r.started_at.replace(":", "").replace("-", "").replace("+0000", "Z")
    base = out_dir / f"{r.suite.name}-{r.profile}-{stamp}"
    html_path, json_path = base.with_suffix(".html"), base.with_suffix(".json")
    html_path.write_text(render_html(r), encoding="utf-8")
    json_path.write_text(json.dumps(report_data(r), indent=2, default=str), encoding="utf-8")
    return html_path, json_path
