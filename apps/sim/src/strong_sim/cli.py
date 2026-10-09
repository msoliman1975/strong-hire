"""Command line for the AI candidate (P13).

    strong-sim suites                          list the suites
    strong-sim plan --suite text-smoke         show the scenarios and the cost estimate
    strong-sim run --suite text-smoke [--scenario ID ...] [--limit-usd 3] [--yes]

`run` prints the estimate and asks before it starts, unless --yes is given.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from strong_core.gateway import Role, get_gateway
from strong_sim.cost import CostMeter, estimate, load_prices
from strong_sim.runner import new_run_id, run_suite
from strong_sim.scenarios import Suite, list_suites, load_suite
from strong_sim.settings import get_sim_settings


def _select(suite: Suite, ids: list[str] | None) -> Suite:
    if not ids:
        return suite
    unknown = set(ids) - {s.id for s in suite.scenarios}
    if unknown:
        sys.exit(f"Unknown scenario ids: {', '.join(sorted(unknown))}")
    return suite.model_copy(update={"scenarios": [s for s in suite.scenarios if s.id in ids]})


def _plan(suite: Suite) -> dict[str, float]:
    print(f"Suite {suite.name}: {len(suite.scenarios)} sessions. {suite.description}".strip())
    for s in suite.scenarios:
        print(
            f"  {s.id:<22} {s.channel:<5} {s.interview_type.value:<15} {s.difficulty.value:<9} "
            f"{s.mode.value:<9} {s.duration_min:>2} min  {s.resume:<20} {s.quality.value:<7} "
            f"{s.behavior.value}"
        )
    est = estimate([s.duration_min for s in suite.scenarios], load_prices())
    print(
        f"Estimated model cost: candidate ${est['candidate_usd']:.2f}, judge "
        f"${est['judge_usd']:.2f}, interviewer and scorer on the main server "
        f"${est['main_server_usd']:.2f}; total about ${est['total_usd']:.2f}."
    )
    minutes = sum(s.duration_min for s in suite.scenarios if s.channel == "voice")
    if minutes:
        print(f"Voice sessions run in real time: about {minutes} minutes for the voice part.")
    return est


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="strong-sim", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("suites", help="list the suites")
    for name in ("plan", "run"):
        p = sub.add_parser(name)
        p.add_argument("--suite", required=True)
        p.add_argument("--scenario", action="append", help="run only these ids (repeatable)")
        if name == "run":
            p.add_argument("--limit-usd", type=float, help="stop when sim-side cost passes this")
            p.add_argument("--yes", action="store_true", help="do not ask before starting")
            p.add_argument("--run-id")
            p.add_argument("--out-dir", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    for noisy in ("httpx", "livekit", "LiteLLM"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.cmd == "suites":
        for name in list_suites():
            print(name)
        return
    suite = _select(load_suite(args.suite), args.scenario)
    _plan(suite)
    if args.cmd == "plan":
        return

    settings = get_sim_settings()
    if args.out_dir:
        settings = settings.model_copy(update={"out_dir": args.out_dir})
    limit = args.limit_usd or settings.cost_limit_usd
    print(f"The run stops if the sim-side model cost passes ${limit:.2f}.")
    if not args.yes and input("Start the run? [y/N] ").strip().lower() not in ("y", "yes"):
        print("Not started.")
        return
    gateway = get_gateway()
    if gateway.config.alias_for(Role.CANDIDATE) == gateway.config.alias_for(Role.INTERVIEWER):
        print("Note: the candidate and the interviewer use the same model alias in this profile.")
    meter = CostMeter(load_prices(), limit_usd=limit)
    run_id = args.run_id or new_run_id(suite.name)
    run_dir, info = asyncio.run(run_suite(suite, settings, gateway, meter, run_id=run_id))
    print(
        f"Run {info['run_id']}: {info['sessions_ok']} of {info['sessions']} sessions finished, "
        f"{info['sessions_all_rules_pass']} passed every judge rule, "
        f"{len(info['order_breaks'])} scorer order breaks, "
        f"sim-side cost ${info['sim_cost_usd']:.2f}."
    )
    print(f"Report: {run_dir / 'report.html'}")
    if info.get("stopped"):
        sys.exit(2)
