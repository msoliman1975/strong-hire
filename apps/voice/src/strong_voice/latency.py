"""Per-turn voice latency: end of the candidate's speech to the agent's first audio out.

The recorder reads the metrics LiveKit Agents attaches to each chat message:

    user message       end_of_turn_delay    end of speech -> turn decision (includes STT)
                       transcription_delay  end of speech -> final transcript
    assistant message  llm_node_ttft        LLM request -> first token
                       tts_node_ttfb        first text to TTS -> first audio chunk
                       e2e_latency          end of speech -> agent starts speaking

Columns in the CSV, all in milliseconds:

    total_ms           e2e_latency
    turn_detection_ms  end_of_turn_delay - transcription_delay (wait after the transcript)
    stt_ms             transcription_delay
    llm_ttft_ms        llm_node_ttft
    tts_ttfb_ms        tts_node_ttfb
    other_ms           total - (end_of_turn_delay + llm_ttft + tts_ttfb): queues, audio buffers

A step LiveKit did not report is left empty (NaN) and skipped in the percentiles. One answer can
arrive as two user messages when the candidate pauses; their metrics are merged.

Report:

    uv run python -m strong_voice.latency report var/latency/local.csv var/latency/hosted.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

GATE_P50_MS = 1000.0
METRICS = ("total_ms", "turn_detection_ms", "stt_ms", "llm_ttft_ms", "tts_ttfb_ms", "other_ms")


@dataclass(frozen=True)
class TurnLatency:
    timestamp: float
    session: str
    profile: str
    turn: int
    total_ms: float
    turn_detection_ms: float
    stt_ms: float
    llm_ttft_ms: float
    tts_ttfb_ms: float
    other_ms: float
    interrupted: bool


def _ms(seconds: Any) -> float:
    return math.nan if seconds is None else round(float(seconds) * 1000, 1)


def build_turn(
    user: Mapping[str, Any],
    assistant: Mapping[str, Any],
    *,
    session: str,
    profile: str,
    turn: int,
    interrupted: bool = False,
) -> TurnLatency | None:
    """Combine a user turn's metrics with the reply's. None without the end-to-end latency."""
    total = _ms(assistant.get("e2e_latency"))
    if math.isnan(total) and "started_speaking_at" in assistant and "stopped_speaking_at" in user:
        # Same formula LiveKit uses for e2e_latency.
        total = _ms(float(assistant["started_speaking_at"]) - float(user["stopped_speaking_at"]))
    if math.isnan(total):
        return None
    eot = _ms(user.get("end_of_turn_delay"))
    stt = _ms(user.get("transcription_delay"))
    ttft = _ms(assistant.get("llm_node_ttft"))
    ttfb = _ms(assistant.get("tts_node_ttfb"))
    return TurnLatency(
        timestamp=round(time.time(), 3),
        session=session,
        profile=profile,
        turn=turn,
        total_ms=total,
        turn_detection_ms=round(max(eot - stt, 0.0), 1),
        stt_ms=stt,
        llm_ttft_ms=ttft,
        tts_ttfb_ms=ttfb,
        other_ms=round(total - (eot + ttft + ttfb), 1),
        interrupted=interrupted,
    )


class LatencyRecorder:
    """Pairs each user turn with the agent reply that follows and appends a CSV row."""

    def __init__(self, path: Path, *, session: str, profile: str) -> None:
        self.path = path
        self.session = session
        self.profile = profile
        self.turns: list[TurnLatency] = []
        self._pending_user: Mapping[str, Any] | None = None

    def on_message(self, role: str, metrics: Mapping[str, Any], interrupted: bool = False) -> None:
        if role == "user":
            # A pause can split one answer into two messages: keep keys from both, newest wins.
            self._pending_user = {**(self._pending_user or {}), **metrics}
            return
        if role != "assistant" or self._pending_user is None:
            return  # the greeting has no user turn before it
        row = build_turn(
            self._pending_user,
            metrics,
            session=self.session,
            profile=self.profile,
            turn=len(self.turns) + 1,
            interrupted=interrupted,
        )
        self._pending_user = None
        if row is not None:
            self.turns.append(row)
            append_rows(self.path, [row])

    def summary(self) -> str:
        return format_report({self.profile: self.turns})


def append_rows(path: Path, rows: Iterable[TurnLatency]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    names = [f.name for f in fields(TurnLatency)]
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=names)
        if new:
            writer.writeheader()
        for row in rows:
            cells = asdict(row)
            writer.writerow(
                {k: "" if isinstance(v, float) and math.isnan(v) else v for k, v in cells.items()}
            )


def read_rows(path: Path) -> list[TurnLatency]:
    with path.open(newline="", encoding="utf-8") as fh:
        out = []
        for r in csv.DictReader(fh):
            out.append(
                TurnLatency(
                    timestamp=float(r["timestamp"]),
                    session=r["session"],
                    profile=r["profile"],
                    turn=int(r["turn"]),
                    interrupted=r["interrupted"] == "True",
                    **{m: float(r[m] or "nan") for m in METRICS},
                )
            )
        return out


def percentile(values: Sequence[float], q: float) -> float:
    """Linear interpolation between closest ranks, q in [0, 100]."""
    if not values:
        return math.nan
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def format_report(by_profile: Mapping[str, Sequence[TurnLatency]]) -> str:
    """Table of p50 and p95 per metric and profile, then the phase 1 gate on hosted."""
    names = list(by_profile)
    head = f"{'metric':<18}" + "".join(f"{n + ' p50':>14}{n + ' p95':>14}" for n in names)
    lines = [head, "-" * len(head)]
    counts = "".join(f"{len(by_profile[n]):>14}{'':>14}" for n in names)
    lines.append(f"{'turns':<18}{counts}")
    for metric in METRICS:
        cells = ""
        for n in names:
            values = [
                v
                for t in by_profile[n]
                if not t.interrupted and not math.isnan(v := float(getattr(t, metric)))
            ]
            cells += f"{percentile(values, 50):>14.0f}{percentile(values, 95):>14.0f}"
        lines.append(f"{metric:<18}{cells}")
    hosted = [t.total_ms for t in by_profile.get("hosted", []) if not t.interrupted]
    if hosted:
        p50 = percentile(hosted, 50)
        verdict = "PASS" if p50 < GATE_P50_MS else "MISS"
        lines.append(
            f"\nPhase 1 gate (hosted p50 total < {GATE_P50_MS:.0f} ms): {verdict}, {p50:.0f} ms"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Voice latency report")
    sub = parser.add_subparsers(dest="cmd", required=True)
    rep = sub.add_parser("report", help="p50 and p95 per profile from latency CSV files")
    rep.add_argument("csv", nargs="+", type=Path)
    args = parser.parse_args(argv)

    by_profile: dict[str, list[TurnLatency]] = {}
    for path in args.csv:
        if not path.exists():
            print(f"missing: {path}")
            continue
        for row in read_rows(path):
            by_profile.setdefault(row.profile, []).append(row)
    if not by_profile:
        print("no latency rows found")
        return 1
    print(format_report(by_profile))
    return 0


if __name__ == "__main__":
    sys.exit(main())
