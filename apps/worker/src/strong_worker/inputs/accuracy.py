"""Per-field extraction accuracy on the fixtures in evals/fixtures/inputs.

    uv run python -m strong_worker.inputs.accuracy [--out report.json] [--only resumes]

Uses the gateway for the current MODEL_PROFILE. Scores are 0.0 to 1.0 per field, averaged over
the fixtures. Text fields match after normalization (or when one contains the other); list fields
use F1 with fuzzy item matching; enum fields must be equal.

Input files can be .txt, .pdf or .docx. Every file is read with `document_text`, the same path
the worker uses, so a PDF case tests the reader and the extractor together.

Resume metrics:
- achievements: F1 of all achievements pooled over the CV, wherever they are filed.
- achievement_attribution: F1 that counts an achievement only when it is under the right role
  (the same company and the same start or end year).
- reading_order: share of role titles and achievements that the reader's text has in the
  expected order. It needs no model, so it measures the file reader alone.
- text_coverage: share of expected companies, titles, achievements, skills and schools that
  the reader's text contains (also no model).
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
from strong_core.schemas import JobPosting, Resume, ResumeRole
from strong_worker.inputs.confidence import grounding, normalize
from strong_worker.inputs.documents import DocumentError, document_text
from strong_worker.inputs.extract import ExtractionError, extract_job_posting, extract_resume

ITEM_MATCH = 0.6
ORDER_PREFIX = 50  # characters of an item that reading_order looks for


def fixtures_dir() -> Path:
    return get_settings().repo_root / "evals" / "fixtures" / "inputs"


INPUT_SUFFIXES = (".txt", ".pdf", ".docx")


@dataclass(frozen=True)
class Case:
    name: str
    text: str
    expected: str
    kind: str  # "text", "pdf" or "docx", from document_text


def load_files(folder: Path) -> list[Case]:
    """Every <name>.json with a <name>.txt, .pdf or .docx, read through `document_text`."""
    cases = []
    for expected_path in sorted(folder.glob("*.json")):
        for suffix in INPUT_SUFFIXES:
            source = expected_path.with_suffix(suffix)
            if source.exists():
                try:
                    kind, text = document_text(source.read_bytes(), source.name)
                except DocumentError as exc:
                    raise DocumentError(f"{source.name}: {exc}") from exc
                cases.append(
                    Case(
                        expected_path.stem,
                        text,
                        expected_path.read_text(encoding="utf-8"),
                        kind,
                    )
                )
                break
    return cases


def load_cases(folder: Path) -> list[tuple[str, str, str]]:
    """(name, input text, expected JSON) for every case in `folder`."""
    return [(c.name, c.text, c.expected) for c in load_files(folder)]


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


def _year(value: str | None) -> str | None:
    return value[:4] if value else None


def _same_role(expected: ResumeRole, actual: ResumeRole) -> bool:
    """The same company, and the same start year or the same end year (None is "current")."""
    if text_score(expected.company, actual.company) != 1.0:
        return False
    return _year(expected.start) == _year(actual.start) or _year(expected.end) == _year(actual.end)


def pair_roles(expected: Resume, actual: Resume) -> list[tuple[ResumeRole, ResumeRole | None]]:
    """Each expected role with the actual role at the same company and dates, used once."""
    free = list(actual.roles)
    pairs: list[tuple[ResumeRole, ResumeRole | None]] = []
    for exp_role in expected.roles:
        found = next((r for r in free if _same_role(exp_role, r)), None)
        if found is not None:
            free.remove(found)
        pairs.append((exp_role, found))
    return pairs


def achievement_attribution(expected: Resume, actual: Resume, threshold: float = 0.5) -> float:
    """F1 over achievements where a match counts only inside the paired role."""
    n_expected = sum(len(r.achievements) for r in expected.roles)
    n_actual = sum(len(r.achievements) for r in actual.roles)
    if n_expected == 0 and n_actual == 0:
        return 1.0
    if n_expected == 0 or n_actual == 0:
        return 0.0
    found = placed = 0
    for exp_role, act_role in pair_roles(expected, actual):
        if act_role is None:
            continue
        found += sum(
            any(_same_item(e, a, threshold) for a in act_role.achievements)
            for e in exp_role.achievements
        )
        placed += sum(
            any(_same_item(a, e, threshold) for e in exp_role.achievements)
            for a in act_role.achievements
        )
    recall, precision = found / n_expected, placed / n_actual
    return 0.0 if recall + precision == 0 else 2 * recall * precision / (recall + precision)


def reading_order(expected: Resume, text: str) -> float:
    """Share of role titles and achievements found in the text in the expected order.

    Each item is looked for after the previous item that was found in order. An item that is
    only found earlier in the text (or not at all) counts as out of order.
    """
    items = [x for r in expected.roles for x in (r.title, *r.achievements)]
    if not items:
        return 1.0
    hay = normalize(text)
    pos = 0
    in_order = 0
    for item in items:
        needle = normalize(item)
        if len(needle) > ORDER_PREFIX:  # the first words; a long line may wrap or be cut
            needle = needle[:ORDER_PREFIX].rsplit(" ", 1)[0] + " "
        at = hay.find(needle, pos)
        if at >= 0:
            in_order += 1
            pos = at + 1
    return in_order / len(items)


def text_coverage(expected: Resume, text: str) -> float:
    """Share of expected companies, titles, achievements, skills and schools whose words are
    all in the reader's text. Needs no model: it finds text the reader lost or broke up."""
    items = [x for r in expected.roles for x in (r.company, r.title, *r.achievements)]
    items += expected.skills + [e.institution for e in expected.education]
    if not items:
        return 1.0
    hay = normalize(text)
    return sum(normalize(item) in hay for item in items) / len(items)


def score_resume(expected: Resume, actual: Resume) -> dict[str, float]:
    pairs = []
    for exp_role in expected.roles:
        found = next(
            (r for r in actual.roles if text_score(exp_role.company, r.company) == 1.0), None
        )
        pairs.append((exp_role, found))
    matched = [(e, a) for e, a in pairs if a is not None]
    dated = [(e, a) for e, a in pair_roles(expected, actual) if a is not None]
    n = max(len(expected.roles), 1)
    return {
        "role_count": float(len(expected.roles) == len(actual.roles)),
        "role_companies": len(matched) / n,
        "role_titles": sum(text_score(e.title, a.title) for e, a in dated) / n,
        "role_dates": sum(e.start == a.start and e.end == a.end for e, a in dated) / n,
        "achievements": list_f1(
            [x for r in expected.roles for x in r.achievements],
            [x for r in actual.roles for x in r.achievements],
            0.5,
        ),
        "achievement_attribution": achievement_attribution(expected, actual),
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
    resume_files: dict[str, float] = field(default_factory=dict)  # PDF and DOCX cases only
    cases: list[dict[str, Any]] = field(default_factory=list)
    profile: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "postings": self.postings,
            "resumes": self.resumes,
            "resume_files": self.resume_files,
            "cases": self.cases,
        }

    def format(self, *, per_case: bool = False) -> str:
        lines = [f"Input extraction accuracy (MODEL_PROFILE={self.profile})"]
        for title, scores in (
            ("Job postings", self.postings),
            ("Resumes (all)", self.resumes),
            ("Resumes (PDF and DOCX files)", self.resume_files),
        ):
            if not scores:
                continue
            lines.append(f"\n{title}")
            lines += [f"  {name:<24} {value:6.2f}" for name, value in scores.items()]
        if per_case:
            lines.append("\nPer case")
            for case in self.cases:
                scores = case.get("scores", {})
                shown = ", ".join(f"{k}={v:.2f}" for k, v in scores.items())
                lines.append(f"  {case['kind']:<8}{case['name']:<32}{shown}")
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


async def run_inputs_eval(
    gateway: ModelGateway, folder: Path | None = None, *, only: str | None = None
) -> Report:
    """Run the extractor on every fixture. `only` is "postings" or "resumes" to run one set."""
    root = folder or fixtures_dir()
    report = Report(profile=gateway.profile)
    posting_rows: list[dict[str, float]] = []
    resume_rows: list[dict[str, float]] = []
    file_rows: list[dict[str, float]] = []

    for case in load_files(root / "postings") if only != "resumes" else []:
        expected = JobPosting.model_validate_json(case.expected)
        try:
            actual = (await extract_job_posting(gateway, case.text)).output
        except ExtractionError as exc:
            report.cases.append({"kind": "posting", "name": case.name, "error": str(exc)})
            actual = JobPosting(company_name="-", title="-")
        scores = score_job_posting(expected, actual)
        posting_rows.append(scores)
        report.cases.append({"kind": "posting", "name": case.name, "scores": scores})

    for case in load_files(root / "resumes") if only != "postings" else []:
        expected_resume = Resume.model_validate_json(case.expected)
        try:
            actual_resume = (await extract_resume(gateway, case.text)).output
        except ExtractionError as exc:
            report.cases.append({"kind": "resume", "name": case.name, "error": str(exc)})
            actual_resume = Resume()
        scores = score_resume(expected_resume, actual_resume)
        scores["reading_order"] = reading_order(expected_resume, case.text)
        scores["text_coverage"] = text_coverage(expected_resume, case.text)
        resume_rows.append(scores)
        if case.kind != "text":
            file_rows.append(scores)
        report.cases.append(
            {"kind": "resume", "name": case.name, "file": case.kind, "scores": scores}
        )

    report.postings = _mean(posting_rows)
    report.resumes = _mean(resume_rows)
    report.resume_files = _mean(file_rows)
    return report


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="Write the full report as JSON to this file.")
    parser.add_argument("--only", choices=["postings", "resumes"], help="Run one set only.")
    parser.add_argument("--cases", action="store_true", help="Print the scores of each case.")
    args = parser.parse_args(argv)
    report = asyncio.run(run_inputs_eval(get_gateway(), only=args.only))
    print(report.format(per_case=args.cases))
    if args.out:
        args.out.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
