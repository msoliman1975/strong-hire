"""Run a named suite against a model profile and write a report to evals/reports/.

    python -m strong_evals run --suite smoke --profile fake
    python -m strong_evals run --suite full --profile local --record --gate

The scripted part scores each gold-set transcript with the scorer and compares it with the human
labels. The simulated part runs text sessions with the simulated candidate. Every model call is
metered into UsageEvent records for the cost metric.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from strong_core.config import Settings, find_repo_root
from strong_core.db.models import UsageEvent
from strong_core.gateway import ModelGateway, Role, build_gateway
from strong_core.gateway.fake import DEFAULT_FIXTURES_DIR
from strong_core.gateway.recorder import RecordingGateway
from strong_core.schemas import HireSignal, Scorecard
from strong_evals import EVALS_DIR
from strong_evals.candidate import Persona
from strong_evals.gap import GapResult, fit_order, run_gap_item
from strong_evals.goldset import GoldLabel, load_goldset
from strong_evals.metrics import (
    Agreement,
    FollowUpCount,
    competency_coverage,
    cost_per_session,
    follow_ups_on_vague,
    mean,
    rubric_pairs,
    score_agreement,
    signal_agreement,
    vague_answer_indexes,
    value_pairs,
)
from strong_evals.session import run_text_session
from strong_evals.stubs import GatewayScorer
from strong_evals.suites import GapSpec, SimulatedSpec, Suite, load_suite, suite_names
from strong_evals.transcripts import ScriptedTranscript, load_transcripts
from strong_evals.usage import MeteredGateway, Prices, load_prices

REPORTS_DIR = EVALS_DIR / "reports"
THRESHOLDS_FILE = EVALS_DIR / "config" / "thresholds.yaml"


@dataclass
class ScriptedResult:
    transcript: ScriptedTranscript
    human: HireSignal | None
    scorer: HireSignal | None
    rubric: Agreement
    values: Agreement
    follow_ups: FollowUpCount
    coverage: float
    cost_usd: Decimal
    error: str | None = None
    detector_hits: int = 0  # vague answers the heuristic found that are labeled vague
    detector_extra: int = 0  # answers the heuristic calls vague that are not labeled vague


@dataclass
class SimulatedResult:
    spec: SimulatedSpec
    turns: list[dict[str, Any]]
    questions_asked: int
    follow_ups: FollowUpCount
    coverage: float
    cost_usd: Decimal
    scorer: HireSignal | None
    error: str | None = None


@dataclass
class MetricResult:
    key: str
    name: str
    value: float | None
    display: str
    threshold: str
    passed: bool | None  # None: information only, or not measured
    source: str
    detail: str = ""


@dataclass
class RunReport:
    suite: Suite
    profile: str
    started_at: str
    duration_s: float
    git_sha: str
    models: dict[str, str]
    prompt_refs: list[str]
    scripted: list[ScriptedResult] = field(default_factory=list)
    simulated: list[SimulatedResult] = field(default_factory=list)
    gap: list[GapResult] = field(default_factory=list)
    metrics: list[MetricResult] = field(default_factory=list)
    recorded: int = 0

    @property
    def errors(self) -> int:
        items: list[ScriptedResult | SimulatedResult | GapResult] = [
            *self.scripted,
            *self.simulated,
            *self.gap,
        ]
        return sum(r.error is not None for r in items)

    @property
    def failed(self) -> list[MetricResult]:
        return [m for m in self.metrics if m.passed is False]


def _session_id(suite: str, item: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"strong-hire-evals/{suite}/{item}")


def _cost(events: list[UsageEvent], sid: uuid.UUID) -> Decimal:
    return cost_per_session(events).get(sid, Decimal(0))


async def run_scripted(
    t: ScriptedTranscript,
    gold: GoldLabel | None,
    base: ModelGateway,
    prices: Prices,
    suite: str,
    refs: dict[str, None],
) -> ScriptedResult:
    sid = _session_id(suite, t.id)
    gw = MeteredGateway(base, prices, sid)
    follow = follow_ups_on_vague(t.turns, t.vague_answers, t.brief.max_probes_per_question)
    coverage = competency_coverage(t.brief, t.turns)
    card: Scorecard | None = None
    error = None
    try:
        card = await GatewayScorer(gw).score(t.brief, t.turns)
    except Exception as e:  # a model that fails validation counts as a miss, not a crash
        error = f"{type(e).__name__}: {e}"[:300]
    refs.update(gw.prompt_refs)
    found, labeled = set(vague_answer_indexes(t.turns)), set(t.vague_answers)
    rubric = values = Agreement(0, 0, 0)
    if card and gold:
        rubric = score_agreement(rubric_pairs(card, gold.scores))
        values = score_agreement(value_pairs(card, gold.value_scores))
    return ScriptedResult(
        transcript=t,
        human=gold.hire_signal if gold else None,
        scorer=card.hire_signal if card else None,
        rubric=rubric,
        values=values,
        follow_ups=follow,
        coverage=coverage,
        cost_usd=_cost(gw.events, sid),
        error=error,
        detector_hits=len(found & labeled),
        detector_extra=len(found - labeled),
    )


async def run_simulated(
    spec: SimulatedSpec, base: ModelGateway, prices: Prices, suite: str, refs: dict[str, None]
) -> SimulatedResult:
    sid = _session_id(suite, spec.id)
    gw = MeteredGateway(base, prices, sid)
    persona = Persona.from_resume_fixture(spec.resume, spec.quality, spec.candidate_name)
    try:
        session = await run_text_session(
            spec.session, persona, gateway=gw, max_questions=spec.max_questions, session_id=sid
        )
    except Exception as e:
        refs.update(gw.prompt_refs)
        return SimulatedResult(
            spec,
            [],
            0,
            FollowUpCount(0, 0),
            0.0,
            _cost(gw.events, sid),
            None,
            f"{type(e).__name__}: {e}"[:300],
        )
    turns = session.turns
    follow = follow_ups_on_vague(
        turns, vague_answer_indexes(turns), session.brief.max_probes_per_question
    )
    signal: HireSignal | None = None
    error = None
    try:
        signal = (await GatewayScorer(gw).score(session.brief, turns)).hire_signal
    except Exception as e:
        error = f"scorer: {type(e).__name__}: {e}"[:300]
    refs.update(gw.prompt_refs)
    asked = {t.question_ref for t in turns if t.question_ref}
    return SimulatedResult(
        spec=spec,
        turns=[t.model_dump(mode="json") for t in turns],
        questions_asked=len(asked),
        follow_ups=follow,
        coverage=competency_coverage(session.brief, turns),
        cost_usd=_cost(gw.events, sid),
        scorer=signal,
        error=error,
    )


async def run_gap(
    spec: GapSpec, base: ModelGateway, prices: Prices, suite: str, refs: dict[str, None]
) -> GapResult:
    sid = _session_id(suite, spec.id)
    gw = MeteredGateway(base, prices, sid)
    result = await run_gap_item(spec, gw)
    result.cost_usd = _cost(gw.events, sid)
    refs.update(gw.prompt_refs)
    return result


def _check(value: float, rule: dict[str, Any]) -> tuple[str, bool | None]:
    if "min" in rule:
        return f">= {rule['min']}", value >= float(rule["min"])
    if "max" in rule:
        return f"<= {rule['max']}", value <= float(rule["max"])
    return "none", None


def compute_metrics(report: RunReport, thresholds: dict[str, dict[str, Any]]) -> list[MetricResult]:
    out: list[MetricResult] = []

    def add(key: str, name: str, value: float | None, display: str, detail: str = "") -> None:
        rule = thresholds.get(key, {})
        source = str(rule.get("source", ""))
        if value is None:
            out.append(MetricResult(key, name, None, "not measured", "", None, source, detail))
            return
        threshold, passed = _check(value, rule)
        out.append(MetricResult(key, name, value, display, threshold, passed, source, detail))

    labeled = [r for r in report.scripted if r.human is not None]
    pairs = [(r.scorer, r.human) for r in labeled if r.scorer is not None and r.human is not None]
    agree = signal_agreement(pairs)
    n = len(labeled)  # a scorer error counts as a miss
    if n:
        note = f"{agree.within_one} of {n} transcripts"
        if n < 60:
            note += f"; the spec asks for a gold set of 60 to 100, this one has {n}"
        add(
            "scorer_within_one_band",
            "Scorer agreement, within one band",
            agree.within_one / n,
            f"{agree.within_one / n:.0%}",
            note,
        )
        add(
            "scorer_exact",
            "Scorer agreement, exact band",
            agree.exact / n,
            f"{agree.exact / n:.0%}",
            f"{agree.exact} of {n} transcripts",
        )
        rub = Agreement(
            sum(r.rubric.n for r in labeled),
            sum(r.rubric.exact for r in labeled),
            sum(r.rubric.within_one for r in labeled),
        )
        add(
            "rubric_within_one_point",
            "Rubric scores within one point",
            rub.within_one_rate if rub.n else None,
            f"{rub.within_one_rate:.0%}",
            f"{rub.within_one} of {rub.n} question and competency scores; exact {rub.exact}",
        )
        val = Agreement(
            sum(r.values.n for r in labeled),
            sum(r.values.exact for r in labeled),
            sum(r.values.within_one for r in labeled),
        )
        labeled_values = sum(len(r.transcript.brief.target_values) > 0 for r in labeled)
        if labeled_values:
            add(
                "value_within_one_point",
                "Company value scores within one point",
                val.within_one_rate if val.n else None,
                f"{val.within_one_rate:.0%}",
                f"{val.within_one} of {val.n} question and value scores; exact {val.exact}; "
                f"{labeled_values} company-mode transcripts",
            )
    else:
        add("scorer_within_one_band", "Scorer agreement, within one band", None, "")

    sims = [r for r in report.simulated if r.error is None or r.turns]
    probed = sum(r.follow_ups.probed for r in sims)
    eligible = sum(r.follow_ups.eligible for r in sims)
    add(
        "follow_up_rate",
        "Follow-up rate on vague answers (simulated)",
        probed / eligible if eligible else None,
        f"{probed / eligible:.0%}" if eligible else "",
        f"{probed} of {eligible} vague answers got a probe",
    )
    cov = [r.coverage for r in sims]
    add(
        "competency_coverage",
        "Coverage of target competencies (simulated)",
        mean(cov) if cov else None,
        f"{mean(cov):.0%}" if cov else "",
        f"mean over {len(cov)} sessions",
    )
    costs = [float(r.cost_usd) for r in sims]
    add(
        "cost_per_session_usd",
        "Cost per session, USD (simulated)",
        mean(costs) if costs else None,
        f"${mean(costs):.4f}" if costs else "",
        f"mean over {len(costs)} sessions from UsageEvent records; "
        f"max ${max(costs, default=0):.4f}",
    )

    gaps = [r for r in report.gap if r.error is None]
    spreads = [r.spread for r in gaps if r.spread is not None]
    if report.gap:
        worst = max(spreads, default=None)
        add(
            "gap_score_spread",
            "Gap analysis: match score spread across runs, points (worst pair)",
            float(worst) if worst is not None else None,
            str(worst),
            f"{len(spreads)} pairs run more than once; {len(report.gap) - len(gaps)} errors",
        )
        passed, checked = fit_order(gaps)
        add(
            "gap_fit_order",
            "Gap analysis: matched resumes score above mismatched ones",
            passed / checked if checked else None,
            f"{passed / checked:.0%}" if checked else "",
            f"{passed} of {checked} matched and mismatched pairs on the same posting",
        )
        costs = [float(r.cost_usd) / len(r.scores) for r in gaps if r.scores]
        add(
            "gap_cost_usd",
            "Gap analysis: cost per run, USD",
            mean(costs) if costs else None,
            f"${mean(costs):.4f}" if costs else "",
            f"mean over {len(costs)} pairs",
        )

    # Reference numbers from the human-written transcripts (not the system under test).
    s_probed = sum(r.follow_ups.probed for r in report.scripted)
    s_eligible = sum(r.follow_ups.eligible for r in report.scripted)
    if s_eligible:
        out.append(
            MetricResult(
                "scripted_follow_up_rate",
                "Follow-up rate in scripted transcripts (reference)",
                s_probed / s_eligible,
                f"{s_probed / s_eligible:.0%}",
                "",
                None,
                "Human-written transcripts. Checks the metric code, not the interviewer",
                f"{s_probed} of {s_eligible} labeled vague answers",
            )
        )
    labeled_vague = sum(len(r.transcript.vague_answers) for r in report.scripted)
    if labeled_vague:
        hits = sum(r.detector_hits for r in report.scripted)
        extra = sum(r.detector_extra for r in report.scripted)
        out.append(
            MetricResult(
                "vague_detector_recall",
                "Vague-answer rule finds labeled vague answers (reference)",
                hits / labeled_vague,
                f"{hits / labeled_vague:.0%}",
                "",
                None,
                "The rule in strong_evals.metrics that the stub interviewer and the simulated "
                "follow-up metric use",
                f"{hits} of {labeled_vague} found; {extra} other answers also flagged",
            )
        )
    if report.scripted:
        s_cov = mean([r.coverage for r in report.scripted])
        out.append(
            MetricResult(
                "scripted_coverage",
                "Coverage in scripted transcripts (reference)",
                s_cov,
                f"{s_cov:.0%}",
                "",
                None,
                "Human-written transcripts. Checks the metric code, not the interviewer",
            )
        )
        s_cost = mean([float(r.cost_usd) for r in report.scripted])
        out.append(
            MetricResult(
                "scorer_cost",
                "Scorer cost per transcript, USD",
                s_cost,
                f"${s_cost:.4f}",
                "",
                None,
                "From UsageEvent records of the scorer calls",
            )
        )
    return out


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=find_repo_root(),
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


async def run_suite(
    suite: Suite,
    profile: str,
    *,
    gateway: ModelGateway | None = None,
    record_dir: Path | None = None,
    goldset: dict[str, GoldLabel] | None = None,
) -> RunReport:
    started = time.perf_counter()
    base = gateway or build_gateway(Settings(model_profile=profile))
    recorder = RecordingGateway(base, record_dir) if record_dir is not None else None
    if recorder is not None:
        base = recorder
    prices = load_prices()
    gold = load_goldset() if goldset is None else goldset
    ids = None if suite.scripted == "all" else suite.scripted
    transcripts = load_transcripts(ids)
    refs: dict[str, None] = {}
    report = RunReport(
        suite=suite,
        profile=base.profile,
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
        duration_s=0.0,
        git_sha=_git_sha(),
        models={r.value: base.config.alias_for(r) for r in Role},
        prompt_refs=[],
    )
    for t in transcripts:
        report.scripted.append(
            await run_scripted(t, gold.get(t.id), base, prices, suite.name, refs)
        )
        print(f"  scripted {t.id}: {report.scripted[-1].scorer or report.scripted[-1].error}")
    for spec in suite.simulated:
        report.simulated.append(await run_simulated(spec, base, prices, suite.name, refs))
        r = report.simulated[-1]
        print(f"  simulated {spec.id}: {len(r.turns)} turns {r.error or ''}")
    for gap_spec in suite.gap:
        report.gap.append(await run_gap(gap_spec, base, prices, suite.name, refs))
        g = report.gap[-1]
        print(f"  gap {gap_spec.id}: scores {g.scores} {g.error or ''}")
    report.prompt_refs = sorted(refs)
    report.recorded = len(recorder.saved) if recorder else 0
    thresholds = yaml.safe_load(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    report.metrics = compute_metrics(report, thresholds)
    report.duration_s = round(time.perf_counter() - started, 1)
    return report


def cmd_run(args: argparse.Namespace) -> int:
    from strong_evals.report import write_report

    suite = load_suite(args.suite)
    record_dir = None
    if args.record:
        record_dir = Path(args.record_dir) if args.record_dir else DEFAULT_FIXTURES_DIR
    print(f"Running suite {suite.name} on profile {args.profile}")
    report = asyncio.run(run_suite(suite, args.profile, record_dir=record_dir))
    html_path, json_path = write_report(report, Path(args.out))
    for m in report.metrics:
        verdict = {True: "PASS", False: "FAIL", None: "info"}[m.passed]
        print(f"  {verdict:4}  {m.name}: {m.display} {m.threshold}")
    print(f"Errors: {report.errors}. Recorded fixtures: {report.recorded}.")
    print(f"Report: {html_path}")
    print(f"Data:   {json_path}")
    if report.errors and report.profile == "fake":
        print("The fake profile must run without errors: the harness itself is broken.")
        return 1
    if args.gate and report.failed:
        print(f"Gate: {len(report.failed)} metric(s) failed.")
        return 1
    return 0


def add_run_parser(sub: Any) -> None:
    p: argparse.ArgumentParser = sub.add_parser("run", help="run a suite and write a report")
    p.add_argument("--suite", default="smoke", help=f"one of: {', '.join(suite_names())}")
    p.add_argument("--profile", default="fake", choices=["fake", "local", "hosted"])
    p.add_argument("--out", default=str(REPORTS_DIR), help="report folder")
    p.add_argument("--record", action="store_true", help="save every model call as a fixture")
    p.add_argument("--record-dir", help="fixture folder (default: the fake model's fixtures)")
    p.add_argument("--gate", action="store_true", help="exit 1 when a metric fails")
    p.set_defaults(func=cmd_run)
