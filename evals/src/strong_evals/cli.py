"""Command line for the eval harness.

python -m strong_evals validate                          # transcripts and gold-set labels
python -m strong_evals run --suite smoke --profile fake  # run a suite, write an HTML report
python -m strong_evals goldset sheet beh-01 --rater ana  # files for a human rater
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from strong_evals.goldset import check_against, read_labels, write_sheet
from strong_evals.transcripts import load_transcripts


def cmd_validate(_: argparse.Namespace) -> int:
    transcripts = load_transcripts()
    by_id = {t.id: t for t in transcripts}
    labels = read_labels()
    check_against(labels, by_id)
    labeled = {lab.transcript_id for lab in labels}
    combos = Counter(
        (t.session.interview_type.value, t.session.level.value, t.quality.value)
        for t in transcripts
    )
    print(f"{len(transcripts)} transcripts, {len(labels)} rater labels on {len(labeled)} of them.")
    for (itype, level, quality), n in sorted(combos.items()):
        print(f"  {itype:15} {level:16} {quality:8} {n}")
    missing = sorted(set(by_id) - labeled)
    if missing:
        print("No gold labels yet: " + ", ".join(missing))
    return 0


def cmd_goldset_sheet(args: argparse.Namespace) -> int:
    transcripts = load_transcripts(args.ids or None)
    for path in write_sheet(transcripts, args.rater, Path(args.out)):
        print(path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="strong_evals", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check transcripts and gold-set labels")
    p.set_defaults(func=cmd_validate)

    gs = sub.add_parser("goldset", help="gold-set tools for human raters")
    gs_sub = gs.add_subparsers(dest="goldset_command", required=True)
    p = gs_sub.add_parser("sheet", help="write transcript text files and a blank CSV to fill")
    p.add_argument("ids", nargs="*", help="transcript ids (default: all)")
    p.add_argument("--rater", required=True, help="your name or initials, used in the CSV")
    p.add_argument("--out", default="var/goldset-sheets", help="output folder")
    p.set_defaults(func=cmd_goldset_sheet)

    from strong_evals.runner import add_run_parser

    add_run_parser(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    sys.stdout.flush()
    return result
