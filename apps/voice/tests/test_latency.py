"""Voice spike latency instrumentation: per-turn breakdown, CSV and p50/p95 report (IV-1)."""

from __future__ import annotations

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


def test_build_turn_needs_every_metric() -> None:
    assert build_turn(USER, {"e2e_latency": 1.0}, session="r", profile="x", turn=1) is None


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
