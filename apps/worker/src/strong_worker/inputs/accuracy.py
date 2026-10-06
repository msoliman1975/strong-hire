"""Per-field extraction accuracy on the fixtures in evals/fixtures/inputs.

    uv run python -m strong_worker.inputs.accuracy [--out report.json]

Uses the gateway for the current MODEL_PROFILE. Scores are 0.0 to 1.0 per field, averaged over
the fixtures. Text fields match after normalization (or when one contains the other); list fields
use F1 with fuzzy item matching; enum fields must be equal.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from strong_core.config import get_settings
from strong_core.gateway import ModelGateway, get_gateway
from strong_core.schemas import JobPosting, Resume
from strong_worker.inputs.confidence import grounding, normalize
from strong_worker.inputs.extract import ExtractionError, extract_job_posting, extract_resume

ITEM_MATCH = 0.6


def fixtures_dir() -> Path:
    return get_settings().repo_root / "evals" / "fixtures" / "inputs"


def load_cases(folder: Path) -> list[tuple[str, str, str]]:
    """(name, input text, expected JSON) for every <name>.txt that has a <name>.json."""
    cases = []
    for text_path in sorted(folder.glob("*.txt")):
        expected = text_path.with_suffix(".json")
        if expected.exists():
            cases.append(
                (
                    text_path.stem,
                    text_path.read_text(encoding="utf-8"),
                    expected.read_text(encoding="utf-8"),
                )
            )
    return cases


def text_score(expected: str | None, actual: str | None) -> float:
    if not expected or not actual:
        return 1.0 if not expected and not actual else 0.0
    exp, act = normalize(expected), normalize(actual)
    if exp in act or act in exp:
        return 1.0
    return 1.0 if max(grounding(expected, act), grounding(actual, exp)) >= ITEM_MATCH else 0.0


def _same_item(a: str, b: str, threshold: float) -> bool:
    return max(grounding(a, normalize(b)), grounding(b, normalize(a))) >= threshold


def list_f1(expected: Sequence[str], actual: Sequence[str], threshold: float = ITEM_MATCH) -> float:
    if not expected and not actual:
        return 1.0
    if not expected or not actual:
        return 0.0
    recall = sum(any(_same_item(e, a, threshold) for a in actual) for e in expected) / len(expected)
    precision = sum(any(_same_item(a, e, threshold) for e in expected) for a in actual) / len(
        actual
    )
    return 0.0 if recall + precision == 0 else 2 * recall * precision / (recall + precision)


def score_job_posting(expected: JobPosting, actual: JobPosting) -> dict[str, float]:
    scores = {
        name: text_score(getattr(expected, name), getattr(actual, name))
        for name in ("company_name", "title", "level_label", "team", "location")
    }
    scores["role_family"] = float(expected.role_family == actual.role_family)
    scores["level"] = float(expected.level == actual.level)
    for name in ("must_have_skills", "nice_to_have_skills"):
        scores[name] = list_f1(getattr(expected, name), getattr(actual, name))
    scores["responsibilities"] = list_f1(expected.responsibilities, actual.responsibilities, 0.5)
    return scores


def score_resume(expected: Resume, actual: Resume) -> dict[str, float]:
    pairs = []
    for exp_role in expected.roles:
        found = next(
            (r for r in actual.roles if text_score(exp_role.company, r.company) == 1.0), None
        )
        pairs.append((exp_role, found))
    matched = [(e, a) for e, a in pairs if a is not None]
    n = max(len(expected.roles), 1)
    return {
        "role_count": float(len(expected.roles) == len(actual.roles)),
        "role_companies": len(matched) / n,
        "role_titles": sum(text_score(e.title, a.title) for e, a in matched) / n,
        "role_dates": sum(e.start == a.start and e.end == a.end for e, a in matched) / n,
        "achievements": list_f1(
            [x for r in expected.roles for x in r.achievements],
            [x for r in actual.roles for x in r.achievements],
            0.5,
        ),
        "skills": list_f1(expected.skills, actual.skills),
        "education": list_f1(
            [e.institution for e in expected.education], [e.institution for e in actual.education]
        ),
        "certifications": list_f1(expected.certifications, actual.certifications),
    }


@dataclass
class Report:
    postings: dict[str, float] = field(default_factory=dict)
    resumes: dict[str, float] = field(default_factory=dict)
    cases: list[dict[str, Any]] = field(default_factory=list)
    profile: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "postings": self.postings,
            "resumes": self.resumes,
            "cases": self.cases,
        }

    def format(self) -> str:
        lines = [f"Input extraction accuracy (MODEL_PROFILE={self.profile})"]
        for title, scores in (("Job postings", self.postings), ("Resumes", self.resumes)):
            lines.append(f"\n{title}")
            lines += [f"  {name:<22} {value:6.2f}" for name, value in scores.items()]
        failed = [c["name"] for c in self.cases if c.get("error")]
        if failed:
            lines.append("\nFailed cases: " + ", ".join(failed))
        return "\n".join(lines)


def _mean(rows: list[dict[str, float]]) -> dict[str, float]:
    totals: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for name, value in row.items():
            totals[name].append(value)
    return {name: round(sum(v) / len(v), 3) for name, v in totals.items()}


async def run_inputs_eval(gateway: ModelGateway, folder: Path | None = None) -> Report:
    root = folder or fixtures_dir()
    report = Report(profile=gateway.profile)
    posting_rows: list[dict[str, float]] = []
    resume_rows: list[dict[str, float]] = []

    for name, text, expected_json in load_cases(root / "postings"):
        expected = JobPosting.model_validate_json(expected_json)
        try:
            actual = (await extract_job_posting(gateway, text)).output
        except ExtractionError as exc:
            report.cases.append({"kind": "posting", "name": name, "error": str(exc)})
            actual = JobPosting(company_name="-", title="-")
        scores = score_job_posting(expected, actual)
        posting_rows.append(scores)
        report.cases.append({"kind": "posting", "name": name, "scores": scores})

    for name, text, expected_json in load_cases(root / "resumes"):
        expected_resume = Resume.model_validate_json(expected_json)
        try:
            actual_resume = (await extract_resume(gateway, text)).output
        except ExtractionError as exc:
            report.cases.append({"kind": "resume", "name": name, "error": str(exc)})
            actual_resume = Resume()
        scores = score_resume(expected_resume, actual_resume)
        resume_rows.append(scores)
        report.cases.append({"kind": "resume", "name": name, "scores": scores})

    report.postings = _mean(posting_rows)
    report.resumes = _mean(resume_rows)
    return report


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="Write the full report as JSON to this file.")
    args = parser.parse_args(argv)
    report = asyncio.run(run_inputs_eval(get_gateway()))
    print(report.format())
    if args.out:
        args.out.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
