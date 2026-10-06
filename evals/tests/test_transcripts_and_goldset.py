"""Scripted transcripts and the gold set (spec, Calibration; IV-2, IV-6, FB-1, FB-2)."""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

import pytest

from strong_core.schemas import Competency, HireSignal, InterviewType, Level
from strong_evals.goldset import (
    COLUMNS,
    GoldSetError,
    check_against,
    consensus,
    read_label_file,
    read_labels,
    write_sheet,
)
from strong_evals.transcripts import TRANSCRIPTS_DIR, Quality, load_transcripts

LAUNCH_COMPANIES = (
    "Google|Amazon|Microsoft|Meta|Apple|Netflix|Nvidia|Salesforce|Uber|Stripe|OpenAI|Anthropic|"
    "Airbnb|Shopify|LinkedIn|Oracle|Adobe|Databricks|Snowflake|Atlassian|eBay"
)


def test_thirty_transcripts_cover_types_levels_and_quality() -> None:
    """IV-2 and IV-6: four interview types, three levels, strong, average and weak answers."""
    transcripts = load_transcripts()
    assert len(transcripts) == 30
    assert {t.session.interview_type for t in transcripts} == set(InterviewType)
    assert {t.session.level for t in transcripts} == {Level.NEW_GRAD, Level.MID, Level.SENIOR}
    assert Counter(t.quality for t in transcripts) == {q: 10 for q in Quality}


def test_transcripts_are_synthetic() -> None:
    """Synthetic people only: no real launch companies and no contact details."""
    pattern = re.compile(rf"\b({LAUNCH_COMPANIES})\b")
    for path in TRANSCRIPTS_DIR.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert not pattern.search(text), path.name
        assert not re.search(r"[\w.]+@[\w.]+\.\w+", text), path.name


def test_weak_transcripts_have_vague_answers_and_strong_mostly_not() -> None:
    """IV-3: the gold set has vague answers for the follow-up metric to measure."""
    transcripts = load_transcripts()
    weak = [t for t in transcripts if t.quality == Quality.WEAK]
    assert all(t.vague_answers for t in weak)
    strong = [t for t in transcripts if t.quality == Quality.STRONG]
    assert sum(len(t.vague_answers) for t in strong) <= len(strong)


def test_every_transcript_has_a_valid_gold_label() -> None:
    """FB-1, FB-2: per-question scores and an overall hire signal for every transcript."""
    transcripts = {t.id: t for t in load_transcripts()}
    labels = read_labels()
    check_against(labels, transcripts)
    gold = consensus(labels)
    assert set(gold) == set(transcripts)
    for tid, label in gold.items():
        asked = set(transcripts[tid].asked_question_refs())
        assert {ref for ref, _ in label.scores} == asked, tid


def test_gold_labels_follow_the_hire_signal_hard_rules() -> None:
    """Spec, Hire signal: a 1 caps at Lean No Hire; Strong Hire needs avg >= 3.5, none below 3."""
    for label in consensus(read_labels()).values():
        scores = list(label.scores.values())
        if 1 in scores:
            assert label.hire_signal.rank >= HireSignal.LEAN_NO_HIRE.rank, label.transcript_id
        if label.hire_signal == HireSignal.STRONG_HIRE:
            assert sum(scores) / len(scores) >= 3.5 and min(scores) >= 3, label.transcript_id


def _csv(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "labels.csv"
    path.write_text(",".join(COLUMNS) + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_label_file_errors_are_clear(tmp_path: Path) -> None:
    with pytest.raises(GoldSetError, match="no overall row"):
        read_label_file(_csv(tmp_path, ["beh-01,ana,q1,ownership,,3,,"]))
    with pytest.raises(GoldSetError, match="score must be 1 to 4"):
        read_label_file(
            _csv(tmp_path, ["beh-01,ana,q1,ownership,,5,,", "beh-01,ana,overall,,,,Hire,"])
        )
    with pytest.raises(GoldSetError, match="bad hire_signal"):
        read_label_file(_csv(tmp_path, ["beh-01,ana,overall,,,,Maybe,"]))
    with pytest.raises(GoldSetError, match="not both"):
        read_label_file(_csv(tmp_path, ["beh-03,ana,q1,ownership,Customer first,3,,"]))


def test_consensus_takes_the_cautious_median(tmp_path: Path) -> None:
    rows = [
        "beh-01,ana,q1,ownership,,4,,",
        "beh-01,ana,overall,,,,Strong Hire,",
        "beh-01,ben,q1,ownership,,3,,",
        "beh-01,ben,overall,,,,Hire,",
    ]
    gold = consensus(read_label_file(_csv(tmp_path, rows)))["beh-01"]
    assert gold.raters == ["ana", "ben"]
    assert gold.hire_signal == HireSignal.HIRE
    assert gold.scores[("q1", Competency.OWNERSHIP)] == 3


def test_iv5_company_mode_transcripts_have_value_labels() -> None:
    """IV-5: company-mode transcripts carry target values, and the gold set scores them."""
    transcripts = {t.id: t for t in load_transcripts()}
    company = sorted(tid for tid, t in transcripts.items() if not t.brief.generic_mode)
    assert company == ["beh-03", "hm-05"]
    gold = consensus(read_labels())
    for tid in company:
        assert transcripts[tid].brief.company_name == "Example Corp"
        assert gold[tid].value_scores, tid
        assert {v for _, v in gold[tid].value_scores} <= set(transcripts[tid].brief.target_values)
    assert all(not gold[tid].value_scores for tid in set(transcripts) - set(company))


def test_value_label_must_be_probed_by_the_question(tmp_path: Path) -> None:
    transcripts = {t.id: t for t in load_transcripts(["beh-03"])}
    rows = ["beh-03,ana,q2,,Own the outcome,3,,", "beh-03,ana,overall,,,,Hire,"]
    with pytest.raises(GoldSetError, match="not probed on q2"):
        check_against(read_label_file(_csv(tmp_path, rows)), transcripts)


def test_rater_sheet_round_trips(tmp_path: Path) -> None:
    """A human rater gets the transcript as text and a CSV with the rows to fill."""
    [t] = load_transcripts(["beh-03"])
    written = write_sheet([t], "ana", tmp_path)
    text = (tmp_path / "beh-03.txt").read_text(encoding="utf-8")
    assert text.startswith("Transcript beh-03")
    assert "Company values: Customer first, Own the outcome" in text
    csv_path = written[-1]
    with csv_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert any(r["value"] == "Customer first" for r in rows)
    for r in rows:
        if r["question_ref"] == "overall":
            r["hire_signal"] = "Hire"
        else:
            r["score"] = "3"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    [labels] = read_label_file(csv_path)
    check_against([labels], {t.id: t})
    assert labels.hire_signal == HireSignal.HIRE
    assert labels.value_scores[("q1", "Own the outcome")] == 3
