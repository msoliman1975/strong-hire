"""Transcript times on the audio clock (SM-6).

During a voice session the candidate's lines get exact times from the mic track (Mouth.say).
The interviewer's lines arrive as captions, which come some time before or after the speech
they belong to. After the session, align_voice() finds the interviewer's speech in the left
track and moves each reply's lines onto it:

- a reply is a run of interviewer lines between two candidate lines;
- its speech is every burst that starts after the candidate line before it ended (less a small
  margin) and before the candidate line after it started;
- the reply's lines share that span in proportion to their length in characters;
- the first line gets latency_ms: its start minus the end of the candidate line before it.

A reply with no speech found keeps its caption times.
"""

from __future__ import annotations

import array
import math
from collections.abc import Sequence

from strong_sim.transcript import Line

FRAME_MS = 10
LOUD_RMS = 300.0
JOIN_GAP_MS = 700  # pauses shorter than this are inside one burst of speech
MIN_BURST_MS = 150  # shorter loud bits are clicks, not speech
EARLY_MS = 200  # a reply may start this much before the candidate line before it ends

Span = tuple[int, int]


def speech_spans(pcm: bytes, rate: int, loud_rms: float = LOUD_RMS) -> list[Span]:
    """Bursts of speech in one mono 16-bit track, as (start, end) ms."""
    samples = array.array("h", pcm[: len(pcm) - len(pcm) % 2])
    step = rate * FRAME_MS // 1000
    spans: list[Span] = []
    for i in range(0, len(samples) - step + 1, step):
        frame = samples[i : i + step : 4]  # every 4th sample is enough for a loudness check
        if math.sqrt(sum(s * s for s in frame) / len(frame)) <= loud_rms:
            continue
        at = i * 1000 // rate
        if spans and at - spans[-1][1] < JOIN_GAP_MS:
            spans[-1] = (spans[-1][0], at + FRAME_MS)
        else:
            spans.append((at, at + FRAME_MS))
    return [s for s in spans if s[1] - s[0] >= MIN_BURST_MS]


def _replies(lines: Sequence[Line]) -> list[list[int]]:
    groups: list[list[int]] = []
    for i, line in enumerate(lines):
        if line.speaker != "interviewer":
            continue
        if groups and groups[-1][-1] == i - 1:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def _is_silence(line: Line) -> bool:
    return line.text == "..." or (line.note or "").startswith("silen")


def align_voice(lines: list[Line], spans: Sequence[Span]) -> None:
    """Move interviewer lines onto the speech in `spans` and set latency_ms. Changes `lines`."""
    used = 0  # spans before this index belong to an earlier reply
    for group in _replies(lines):
        first, last = group[0], group[-1]
        before = lines[first - 1] if first > 0 else None
        after = lines[last + 1] if last + 1 < len(lines) else None
        lo = before.end_ms - EARLY_MS if before else 0
        hi = after.start_ms if after else math.inf
        mine: list[Span] = []
        while used < len(spans) and spans[used][0] < hi:
            if spans[used][0] >= lo:
                mine.append(spans[used])
            used += 1
        if not mine:
            continue
        start, end = mine[0][0], max(e for _, e in mine)
        weights = [max(1, len(lines[i].text)) for i in group]
        total, done = sum(weights), 0
        for i, weight in zip(group, weights, strict=True):
            line = lines[i]
            line.start_ms = start + (end - start) * done // total
            done += weight
            line.end_ms = start + (end - start) * done // total
        if before is not None and not _is_silence(before):
            lines[first].latency_ms = start - before.end_ms


def latencies(lines: Sequence[Line]) -> list[int]:
    return [line.latency_ms for line in lines if line.latency_ms is not None]
