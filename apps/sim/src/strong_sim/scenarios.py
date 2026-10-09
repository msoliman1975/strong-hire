"""Scenarios and suites (P13).

A suite file, evals/scenarios/<name>.yaml, lists scenarios by hand, generates them by pairwise
selection, or both:

    name: text-smoke
    description: ...
    scenarios:                       # by hand
      - {id: beh-strong, interview_type: behavioral, quality: strong}
    pairwise:                        # every pair of values appears in at least one scenario
      seed: 7
      dimensions:
        interview_type: [behavioral, case]
        difficulty: [friendly, tough]
      fixed: {channel: text}         # the same for every generated scenario

Any field left out takes its default from Scenario.
"""

from __future__ import annotations

import itertools
import random
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from strong_core.config import find_repo_root
from strong_core.schemas import Difficulty, InterviewType, Level, Mode, SessionConfig

SCENARIOS_DIR = find_repo_root() / "evals" / "scenarios"
FIXTURES_DIR = find_repo_root() / "evals" / "fixtures" / "inputs"


class Quality(StrEnum):
    STRONG = "strong"
    AVERAGE = "average"
    WEAK = "weak"


class Behavior(StrEnum):
    NORMAL = "normal"
    LONG_ANSWERS = "long_answers"
    ONE_LINE_ANSWERS = "one_line_answers"
    OFF_TOPIC = "off_topic"
    ASKS_TO_REPEAT = "asks_to_repeat"
    SILENT = "silent"
    INTERRUPTS = "interrupts"  # voice only
    ARGUES = "argues"
    MANY_QUESTIONS_BACK = "many_questions_back"
    PROMPT_INJECTION = "prompt_injection"
    DROPS_CONNECTION = "drops_connection"  # voice only


VOICE_ONLY = frozenset({Behavior.INTERRUPTS, Behavior.DROPS_CONNECTION})

Channel = Literal["text", "voice"]


class ResumeFixture(BaseModel):
    posting: str
    level: Level


# The posting each resume fixture is meant for, and the level it confirms at setup.
RESUMES: dict[str, ResumeFixture] = {
    "backend-senior": ResumeFixture(posting="swe-stripe-backend", level=Level.SENIOR),
    "ml-engineer-staff": ResumeFixture(
        posting="data-databricks-ml-serving", level=Level.STAFF_PRINCIPAL
    ),
    "new-grad-swe": ResumeFixture(posting="swe-northwind-newgrad", level=Level.NEW_GRAD),
    "product-manager-mid": ResumeFixture(posting="pm-shopify-checkout", level=Level.MID),
    "product-designer-senior": ResumeFixture(
        posting="design-airbnb-product-designer", level=Level.SENIOR
    ),
    "tpm-career-changer": ResumeFixture(posting="tpm-harbor-robotics", level=Level.MID),
}

# Synthetic names only. A scenario gets one by its position in the suite.
NAMES = (
    "Ada Venn", "Tomas Ruel", "Mira Ostrand", "Kofi Lindqvist", "Ben Halloway", "Ines Marrow",
    "Joel Tamsin", "Priya Calder", "Cal Dunmore", "Nadia Fenwick", "Owen Strand", "Lila Burrows",
    "Sami Okafor", "Rhea Duval", "Theo Marsh", "Yara Quint",
)  # fmt: skip


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    channel: Channel = "text"
    interview_type: InterviewType = InterviewType.BEHAVIORAL
    difficulty: Difficulty = Difficulty.REALISTIC
    mode: Mode = Mode.REALISTIC
    duration_min: Literal[10, 30, 45] = 30
    resume: str = "backend-senior"
    quality: Quality = Quality.AVERAGE
    behavior: Behavior = Behavior.NORMAL
    candidate_name: str = ""

    @property
    def fixture(self) -> ResumeFixture:
        return RESUMES[self.resume]

    def session_config(self) -> SessionConfig:
        return SessionConfig(
            interview_type=self.interview_type,
            difficulty=self.difficulty,
            mode=self.mode,
            duration_min=self.duration_min,
            level=self.fixture.level,
        )

    def check(self) -> None:
        if self.resume not in RESUMES:
            raise ValueError(f"{self.id}: unknown resume fixture {self.resume!r}")
        if self.behavior in VOICE_ONLY and self.channel != "voice":
            raise ValueError(f"{self.id}: behavior {self.behavior} needs the voice channel")


class Suite(BaseModel):
    name: str
    description: str = ""
    scenarios: list[Scenario]


def pairwise(
    dimensions: Mapping[str, Sequence[Any]], seed: int = 7, tries: int = 50
) -> list[dict[str, Any]]:
    """A small set of rows in which every pair of values from two dimensions appears at least once.

    Greedy: each new row is the best of `tries` random rows, scored by how many uncovered pairs it
    covers, starting from an uncovered pair so every row makes progress. Same seed, same rows.
    """
    names = list(dimensions)
    values = {n: list(dimensions[n]) for n in names}
    if len(names) < 2:
        return [{names[0]: v} for v in values[names[0]]] if names else []
    uncovered = {
        ((a, va), (b, vb))
        for a, b in itertools.combinations(names, 2)
        for va in values[a]
        for vb in values[b]
    }
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []

    def covers(row: dict[str, Any]) -> set[tuple[tuple[str, Any], tuple[str, Any]]]:
        return {((a, row[a]), (b, row[b])) for a, b in itertools.combinations(names, 2)} & uncovered

    while uncovered:
        (a, va), (b, vb) = min(uncovered, key=repr)
        best: dict[str, Any] | None = None
        best_n = -1
        for _ in range(tries):
            row = {n: rng.choice(values[n]) for n in names}
            row[a], row[b] = va, vb
            n = len(covers(row))
            if n > best_n:
                best, best_n = row, n
        assert best is not None
        rows.append(best)
        uncovered -= covers(best)
    return rows


def load_suite(name_or_path: str, folder: Path = SCENARIOS_DIR) -> Suite:
    path = Path(name_or_path)
    if not path.suffix:
        path = folder / f"{name_or_path}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows: list[dict[str, Any]] = list(data.get("scenarios") or [])
    spec = data.get("pairwise")
    if spec:
        fixed = spec.get("fixed") or {}
        for i, row in enumerate(pairwise(spec["dimensions"], seed=spec.get("seed", 7)), start=1):
            rows.append({"id": f"{spec.get('prefix', 'pw')}-{i:02d}", **fixed, **row})
    scenarios = []
    for i, row in enumerate(rows):
        scenario = Scenario.model_validate(row)
        if not scenario.candidate_name:
            scenario.candidate_name = NAMES[i % len(NAMES)]
        scenario.check()
        scenarios.append(scenario)
    ids = [s.id for s in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError(f"suite {path.stem}: duplicate scenario ids")
    return Suite(name=data.get("name", path.stem), description=data.get("description", ""),
                 scenarios=scenarios)  # fmt: skip


def list_suites(folder: Path = SCENARIOS_DIR) -> list[str]:
    return sorted(p.stem for p in folder.glob("*.yaml"))
