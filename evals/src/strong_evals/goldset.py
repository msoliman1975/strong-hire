"""Gold set: human scores for transcripts (spec, Calibration).

Raters fill CSV files in evals/goldset/labels/. Each rater can use their own file. Columns:

    transcript_id, rater, question_ref, competency, score, hire_signal, note

- One row per asked question and competency: question_ref, competency and score (1 to 4).
- One row per transcript with question_ref = "overall" and the hire_signal
  (Strong Hire, Hire, Lean Hire, Lean No Hire, No Hire). competency and score stay empty.

`python -m strong_evals goldset sheet <transcript_id> --rater <name>` writes a readable transcript
and a CSV with the rows to fill. `python -m strong_evals validate` checks every label file.
"""

from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from strong_core.schemas import Competency, HireSignal, Phase, Speaker
from strong_evals import EVALS_DIR
from strong_evals.transcripts import ScriptedTranscript

GOLDSET_DIR = EVALS_DIR / "goldset"
LABELS_DIR = GOLDSET_DIR / "labels"
OVERALL = "overall"
COLUMNS = ["transcript_id", "rater", "question_ref", "competency", "score", "hire_signal", "note"]


class GoldSetError(ValueError):
    pass


@dataclass
class RaterLabels:
    """One rater's labels for one transcript."""

    transcript_id: str
    rater: str
    hire_signal: HireSignal | None = None
    scores: dict[tuple[str, Competency], int] = field(default_factory=dict)


@dataclass
class GoldLabel:
    """Consensus over all raters of one transcript."""

    transcript_id: str
    raters: list[str]
    hire_signal: HireSignal
    scores: dict[tuple[str, Competency], int]


def read_label_file(path: Path) -> list[RaterLabels]:
    by_key: dict[tuple[str, str], RaterLabels] = {}
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or list(reader.fieldnames) != COLUMNS:
            raise GoldSetError(f"{path.name}: header must be {','.join(COLUMNS)}")
        for n, row in enumerate(reader, start=2):
            where = f"{path.name} line {n}"
            tid, rater = row["transcript_id"].strip(), row["rater"].strip()
            if not tid or not rater:
                raise GoldSetError(f"{where}: transcript_id and rater are required")
            labels = by_key.setdefault((tid, rater), RaterLabels(tid, rater))
            ref = row["question_ref"].strip()
            if ref == OVERALL:
                if labels.hire_signal is not None:
                    raise GoldSetError(f"{where}: second overall row for {tid} by {rater}")
                try:
                    labels.hire_signal = HireSignal(row["hire_signal"].strip())
                except ValueError as e:
                    raise GoldSetError(f"{where}: bad hire_signal {row['hire_signal']!r}") from e
                continue
            try:
                competency = Competency(row["competency"].strip())
                score = int(row["score"])
            except ValueError as e:
                raise GoldSetError(f"{where}: bad competency or score") from e
            if not 1 <= score <= 4:
                raise GoldSetError(f"{where}: score must be 1 to 4")
            if (ref, competency) in labels.scores:
                raise GoldSetError(f"{where}: duplicate row for {ref}/{competency.value}")
            labels.scores[(ref, competency)] = score
    for labels in by_key.values():
        if labels.hire_signal is None:
            raise GoldSetError(
                f"{path.name}: {labels.transcript_id} by {labels.rater} has no overall row"
            )
    return list(by_key.values())


def read_labels(folder: Path = LABELS_DIR) -> list[RaterLabels]:
    out: list[RaterLabels] = []
    seen: set[tuple[str, str]] = set()
    for path in sorted(folder.glob("*.csv")):
        for labels in read_label_file(path):
            key = (labels.transcript_id, labels.rater)
            if key in seen:
                raise GoldSetError(f"{path.name}: {key[0]} by {key[1]} is labeled twice")
            seen.add(key)
            out.append(labels)
    return out


def check_against(
    labels: Iterable[RaterLabels], transcripts: dict[str, ScriptedTranscript]
) -> None:
    """Every label must point at an asked question and one of that question's competencies."""
    for lab in labels:
        t = transcripts.get(lab.transcript_id)
        if t is None:
            raise GoldSetError(f"label for unknown transcript {lab.transcript_id}")
        asked = set(t.asked_question_refs())
        for ref, competency in lab.scores:
            if ref not in asked:
                raise GoldSetError(f"{lab.transcript_id}/{lab.rater}: {ref} was not asked")
            if competency not in t.question(ref).competencies:
                raise GoldSetError(
                    f"{lab.transcript_id}/{lab.rater}: {competency.value} is not scored on {ref}"
                )


def consensus(labels: Iterable[RaterLabels]) -> dict[str, GoldLabel]:
    """Median over raters. For an even count, the lower (more cautious) middle value."""
    grouped: dict[str, list[RaterLabels]] = defaultdict(list)
    for lab in labels:
        grouped[lab.transcript_id].append(lab)
    out: dict[str, GoldLabel] = {}
    for tid, group in grouped.items():
        ranks = [lab.hire_signal.rank for lab in group if lab.hire_signal is not None]
        signal = list(HireSignal)[statistics.median_high(ranks)]
        keys = {k for lab in group for k in lab.scores}
        scores = {
            k: statistics.median_low([lab.scores[k] for lab in group if k in lab.scores])
            for k in keys
        }
        out[tid] = GoldLabel(tid, sorted(lab.rater for lab in group), signal, scores)
    return out


def load_goldset(folder: Path = LABELS_DIR) -> dict[str, GoldLabel]:
    return consensus(read_labels(folder))


# --- rater sheets -------------------------------------------------------------------------------


def render_transcript_text(t: ScriptedTranscript) -> str:
    """A plain text view of a transcript for human raters."""
    s = t.session
    lines = [
        f"Transcript {t.id}: {t.title}",
        f"Interview type: {s.interview_type.value}. Level: {s.level.value}. "
        f"Difficulty: {s.difficulty.value}. Mode: {s.mode.value}.",
        "Target competencies: " + ", ".join(c.value for c in t.brief.target_competencies),
        "",
    ]
    phase: Phase | None = None
    for turn in t.turns:
        if turn.phase != phase:
            phase = turn.phase
            lines += ["", f"--- {phase.value} ---"]
        who = "Interviewer" if turn.speaker == Speaker.INTERVIEWER else "Candidate"
        ref = f" [{turn.question_ref}]" if turn.question_ref else ""
        lines.append(f"{who}{ref}: {turn.text}")
    lines += ["", "Questions to score:"]
    for ref in t.asked_question_refs():
        q = t.question(ref)
        lines.append(f"  {ref}: {q.text} ({', '.join(c.value for c in q.competencies)})")
    lines += [
        "",
        "Rubric: 1 = no evidence, 2 = weak, 3 = meets the bar for this level, 4 = above the bar.",
        "Hire signal: Strong Hire, Hire, Lean Hire, Lean No Hire, No Hire.",
    ]
    return "\n".join(lines) + "\n"


def blank_rows(t: ScriptedTranscript, rater: str) -> list[dict[str, str]]:
    rows = []
    for ref in t.asked_question_refs():
        for c in t.question(ref).competencies:
            rows.append(
                dict.fromkeys(COLUMNS, "")
                | {
                    "transcript_id": t.id,
                    "rater": rater,
                    "question_ref": ref,
                    "competency": c.value,
                }
            )
    rows.append(
        dict.fromkeys(COLUMNS, "")
        | {"transcript_id": t.id, "rater": rater, "question_ref": OVERALL}
    )
    return rows


def write_sheet(transcripts: list[ScriptedTranscript], rater: str, out_dir: Path) -> list[Path]:
    """Write <id>.txt per transcript and one <rater>.csv with the rows to fill."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for t in transcripts:
        path = out_dir / f"{t.id}.txt"
        path.write_text(render_transcript_text(t), encoding="utf-8")
        written.append(path)
    csv_path = out_dir / f"{rater}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for t in transcripts:
            writer.writerows(blank_rows(t, rater))
    written.append(csv_path)
    return written
