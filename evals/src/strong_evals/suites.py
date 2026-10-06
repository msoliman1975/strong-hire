"""Named eval suites: evals/suites/<name>.yaml.

name: smoke
description: A fast check that the harness runs end to end.
include: [other-suite]         # optional: add the items of other suites
scripted: [beh-01, hm-02]      # transcript ids, or "all"
simulated:
  - id: sim-beh-weak
    resume: backend-senior     # evals/fixtures/inputs/resumes/<resume>.json
    quality: weak
    candidate_name: Sam Ortega
    max_questions: 3           # optional cap on core questions
    session: {interview_type: behavioral, difficulty: realistic, mode: realistic,
              duration_min: 30, level: senior}
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from strong_core.schemas import Contract, SessionConfig
from strong_evals import EVALS_DIR
from strong_evals.transcripts import Quality

SUITES_DIR = EVALS_DIR / "suites"


class SimulatedSpec(Contract):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    resume: str
    quality: Quality
    candidate_name: str
    session: SessionConfig
    max_questions: int | None = Field(default=None, ge=1)


class Suite(Contract):
    name: str
    description: str
    include: list[str] = Field(default_factory=list)
    scripted: list[str] | Literal["all"] = Field(default_factory=list)
    simulated: list[SimulatedSpec] = Field(default_factory=list)


def suite_names(folder: Path = SUITES_DIR) -> list[str]:
    return sorted(p.stem for p in folder.glob("*.yaml"))


def load_suite(name: str, folder: Path = SUITES_DIR) -> Suite:
    path = folder / f"{name}.yaml"
    if not path.exists():
        raise SystemExit(f"No suite {name!r}. Known: {', '.join(suite_names(folder))}")
    suite = Suite.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if suite.name != name:
        raise SystemExit(f"{path.name}: name must be {name!r}")
    for other in suite.include:
        sub = load_suite(other, folder)
        if sub.scripted == "all" or suite.scripted == "all":
            suite.scripted = "all"
        else:
            suite.scripted = list(dict.fromkeys([*suite.scripted, *sub.scripted]))
        known = {s.id for s in suite.simulated}
        suite.simulated += [s for s in sub.simulated if s.id not in known]
    return suite
