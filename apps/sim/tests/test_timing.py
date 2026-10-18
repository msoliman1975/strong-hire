"""SM-6: transcript times on the audio clock, and SM-9 response times, from synthetic audio."""

from __future__ import annotations

import array
import math

from strong_sim.audio import Recorder
from strong_sim.timing import align_voice, latencies, speech_spans
from strong_sim.transcript import Line

RATE = 24_000
TOLERANCE_MS = 150


def _track(total_ms: int, speech: list[tuple[int, int]]) -> bytes:
    """A mono 16-bit track: a 220 Hz tone in each (start, end) ms span, silence elsewhere."""
    samples = array.array("h", bytes(total_ms * RATE // 1000 * 2))
    for start, end in speech:
        for i in range(start * RATE // 1000, end * RATE // 1000):
            samples[i] = int(3000 * math.sin(2 * math.pi * 220 * i / RATE))
    return samples.tobytes()


def _near(got: int, want: int) -> bool:
    return abs(got - want) <= TOLERANCE_MS


def test_speech_spans_join_short_pauses_and_drop_clicks() -> None:
    pcm = _track(14_000, [(1_000, 4_000), (9_000, 10_000), (10_400, 12_000), (13_000, 13_050)])
    spans = speech_spans(pcm, RATE)
    assert len(spans) == 2  # the 400 ms pause is inside one burst; the 50 ms click is dropped
    (a0, a1), (b0, b1) = spans
    assert _near(a0, 1_000) and _near(a1, 4_000) and _near(b0, 9_000) and _near(b1, 12_000)


def test_align_voice_moves_interviewer_lines_onto_their_speech() -> None:
    """SM-6: caption times move onto the speech within 150 ms; SM-9: latency per reply."""
    left = _track(22_000, [(1_000, 4_000), (9_000, 12_000), (19_500, 21_000)])
    lines = [
        Line(speaker="interviewer", text="Hello there, welcome.", start_ms=500, end_ms=500),
        Line(speaker="candidate", text="Thanks, happy to be here.", start_ms=4_800, end_ms=8_000),
        Line(speaker="interviewer", text="Good.", start_ms=8_100, end_ms=8_100),
        Line(
            speaker="interviewer",
            text="Tell me about a system you scaled.",
            start_ms=8_100,
            end_ms=8_100,
        ),
        Line(
            speaker="candidate", text="...", start_ms=12_500, end_ms=18_500, note="silent for 6 s"
        ),
        Line(speaker="interviewer", text="Take your time.", start_ms=19_000, end_ms=19_000),
    ]
    align_voice(lines, speech_spans(left, RATE))

    first, _, good, scaled, _, after_silence = lines
    assert _near(first.start_ms, 1_000) and _near(first.end_ms, 4_000)
    assert first.latency_ms is None  # nothing before the opening line
    # Two lines share one reply's speech, in proportion to their length, without a gap.
    assert _near(good.start_ms, 9_000) and _near(scaled.end_ms, 12_000)
    assert good.end_ms == scaled.start_ms and good.end_ms - good.start_ms < 1_000
    assert good.latency_ms is not None and _near(good.latency_ms, 1_000)
    assert scaled.latency_ms is None  # only the first line of a reply
    # After a silent candidate turn the gap is the harness waiting, not interviewer latency.
    assert _near(after_silence.start_ms, 19_500) and after_silence.latency_ms is None
    assert latencies(lines) == [good.latency_ms]


def test_a_reply_without_speech_keeps_its_caption_times() -> None:
    lines = [
        Line(speaker="interviewer", text="Hi", start_ms=700, end_ms=700),
        Line(speaker="candidate", text="Hello", start_ms=2_000, end_ms=3_000),
    ]
    align_voice(lines, [])
    assert (lines[0].start_ms, lines[0].latency_ms) == (700, None)


def test_an_interrupted_reply_keeps_the_speech_that_started_before_the_candidate() -> None:
    """Voice behavior `interrupts`: the candidate talks over the interviewer."""
    left = _track(12_000, [(1_000, 5_000), (8_000, 9_000)])
    lines = [
        Line(speaker="interviewer", text="So tell me", start_ms=900, end_ms=900),
        Line(
            speaker="candidate",
            text="Sure!",
            start_ms=2_500,
            end_ms=4_000,
            note="interrupted the interviewer",
        ),
        Line(speaker="interviewer", text="Let me finish.", start_ms=7_000, end_ms=7_000),
    ]
    align_voice(lines, speech_spans(left, RATE))
    assert _near(lines[0].start_ms, 1_000) and _near(lines[0].end_ms, 5_000)
    assert _near(lines[2].start_ms, 8_000)
    assert lines[2].latency_ms is not None and _near(lines[2].latency_ms, 4_000)


def test_recorder_does_not_drift_on_jitter_and_fills_real_gaps() -> None:
    """SM-6: late frames (jitter) do not push the track ahead; a reconnect gap is silence."""
    rec = Recorder(RATE)
    rec.t0 = 100.0
    frame = bytes(RATE // 100 * 2)  # 10 ms
    rec.add(0, frame, at=100.0 + 1.0)  # the first frame, 1 s after the start
    assert rec.ms(0) == 1_010
    for i in range(1, 1_000):  # 10 s of frames, each up to 40 ms late
        rec.add(0, frame, at=101.0 + i * 0.01 + (0.04 if i % 3 else 0.0))
    assert rec.ms(0) == 11_000  # exactly 1 s + 1,000 frames: no padding for jitter
    rec.add(0, frame, at=100.0 + 15.0)  # a 4 s gap, as after a dropped connection
    assert rec.ms(0) == 15_010
