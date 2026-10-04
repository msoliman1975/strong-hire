"""Voice spike latency instrumentation: per-turn breakdown, CSV and p50/p95 report (IV-1)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from strong_voice.latency import (
    LatencyRecorder,
    build_turn,
    format_report,
    main,
    percentile,
    read_rows,
)

USER = {"end_of_turn_delay": 0.45, "transcription_delay": 0.20}
REPLY = {"e2e_latency": 0.90, "llm_node_ttft": 0.25, "tts_node_ttfb": 0.12}


def test_build_turn_breaks_down_end_of_speech_to_first_audio() -> None:
    t = build_turn(USER, REPLY, session="r", profile="hosted", turn=1)
    assert t is not None
    assert t.total_ms == 900.0
    assert t.stt_ms == 200.0
    assert t.turn_detection_ms == 250.0
    assert t.llm_ttft_ms == 250.0
    assert t.tts_ttfb_ms == 120.0
    assert t.other_ms == pytest.approx(900 - (450 + 250 + 120))


def test_build_turn_needs_only_the_end_to_end_latency() -> None:
    assert build_turn(USER, {"llm_node_ttft": 0.2}, session="r", profile="x", turn=1) is None
    t = build_turn({}, {"e2e_latency": 1.0}, session="r", profile="x", turn=1)
    assert t is not None
    assert t.total_ms == 1000.0
    assert math.isnan(t.stt_ms)
    assert math.isnan(t.llm_ttft_ms)
    fallback = build_turn(
        {"stopped_speaking_at": 10.0},
        {"started_speaking_at": 11.25},
        session="r",
        profile="x",
        turn=1,
    )
    assert fallback is not None
    assert fallback.total_ms == 1250.0


def test_partial_rows_round_trip_and_are_skipped_in_percentiles(tmp_path: Path) -> None:
    rec = LatencyRecorder(tmp_path / "local.csv", session="room", profile="local")
    rec.on_message("user", {})
    rec.on_message("assistant", {"e2e_latency": 2.0})
    rec.on_message("user", USER)
    rec.on_message("assistant", REPLY)
    rows = read_rows(tmp_path / "local.csv")
    assert math.isnan(rows[0].stt_ms)
    assert rows[1].stt_ms == 200.0
    text = format_report({"local": rows})
    assert "stt_ms" in text


def test_split_answer_merges_user_metrics(tmp_path: Path) -> None:
    rec = LatencyRecorder(tmp_path / "x.csv", session="room", profile="local")
    rec.on_message("user", {"transcription_delay": 0.3, "end_of_turn_delay": 0.6})
    rec.on_message("user", {"stopped_speaking_at": 12.0})  # second half of the same answer
    rec.on_message("assistant", REPLY)
    assert rec.turns[0].stt_ms == 300.0


def test_recorder_pairs_user_and_reply_and_skips_greeting(tmp_path: Path) -> None:
    path = tmp_path / "local.csv"
    rec = LatencyRecorder(path, session="room", profile="local")
    rec.on_message("assistant", REPLY)  # greeting: no user turn before it
    rec.on_message("user", USER)
    rec.on_message("assistant", REPLY)
    rec.on_message("user", USER)
    rec.on_message("assistant", REPLY, interrupted=True)
    assert [t.turn for t in rec.turns] == [1, 2]
    rows = read_rows(path)
    assert len(rows) == 2
    assert rows[1].interrupted
    assert "local p50" in rec.summary()


def test_percentile_interpolates() -> None:
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([5], 95) == 5
    assert percentile(list(range(1, 101)), 95) == pytest.approx(95.05)


def test_report_compares_profiles_and_checks_the_gate(tmp_path: Path) -> None:
    fast = {**REPLY, "e2e_latency": 0.8}
    slow = {**REPLY, "e2e_latency": 3.0}
    local = LatencyRecorder(tmp_path / "local.csv", session="a", profile="local")
    hosted = LatencyRecorder(tmp_path / "hosted.csv", session="b", profile="hosted")
    for _ in range(3):
        local.on_message("user", USER)
        local.on_message("assistant", slow)
        hosted.on_message("user", USER)
        hosted.on_message("assistant", fast)
    text = format_report({"local": local.turns, "hosted": hosted.turns})
    assert "local p95" in text
    assert "hosted p50" in text
    assert "PASS, 800 ms" in text
    assert main(["report", str(tmp_path / "local.csv"), str(tmp_path / "hosted.csv")]) == 0


def test_report_shows_a_miss() -> None:
    rec = LatencyRecorder(Path("unused.csv"), session="a", profile="hosted")
    t = build_turn(USER, {**REPLY, "e2e_latency": 1.4}, session="a", profile="hosted", turn=1)
    assert t is not None
    rec.turns.append(t)
    assert "MISS, 1400 ms" in rec.summary()


def test_stt_time_comes_from_the_adapter_when_given(tmp_path: Path) -> None:
    rec = LatencyRecorder(tmp_path / "x.csv", session="room", profile="local")
    rec.on_message("user", {**USER, "transcription_delay": 0.0})
    rec.on_stt(1.5)
    rec.on_message("assistant", REPLY)
    t = rec.turns[0]
    assert t.stt_ms == 1500.0
    assert t.turn_detection_ms == 450.0
    assert t.other_ms == pytest.approx(900 - (450 + 1500 + 250 + 120))


def test_warmup_recorder_writes_no_file(tmp_path: Path) -> None:
    rec = LatencyRecorder(None, session="warmup-local-1", profile="local")
    rec.on_message("user", USER)
    rec.on_message("assistant", REPLY)
    assert len(rec.turns) == 1
    assert list(tmp_path.iterdir()) == []
