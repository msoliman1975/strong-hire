"""Simulated candidate for latency runs. Joins a room, speaks recorded answers, measures replies.

    python -m strong_voice.caller --sessions 5

Each session joins a new room, so the worker starts a fresh two-question interview. The caller
waits for the greeting, speaks answer 1, waits for the reply, speaks answer 2, waits again.
Answers are rendered once through the tts role. The agent writes the per-turn breakdown to its
latency CSV; the caller prints what it heard from outside: end of its speech to first reply audio.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import math
import statistics
import sys
import time
import uuid
from array import array

from livekit import rtc

from strong_core.gateway import ModelGateway, Role, get_gateway
from strong_voice.devserver import make_token
from strong_voice.latency import percentile
from strong_voice.settings import get_voice_settings

ANSWERS = (
    "I led the rebuild of our billing service. I wrote the design, split the work across three "
    "engineers, and we cut failed payments by forty percent in two months.",
    "A teammate wanted to rewrite our API from scratch. I asked for one week to measure the real "
    "problems, we found two slow queries, fixed them, and agreed to skip the rewrite.",
)
FRAME_MS = 10
LOUD_RMS = 300.0
QUIET_AFTER_S = 1.5
DEFAULT_TIMEOUT_S = 30.0


def _rms(frame: rtc.AudioFrame) -> float:
    samples = array("h", bytes(frame.data))
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class AgentEar:
    """Tracks when the agent's audio is loud, from the subscribed audio track."""

    def __init__(self, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self.timeout_s = timeout_s
        self.last_loud = 0.0
        self.loud_times: list[float] = []
        self.tasks: list[asyncio.Task[None]] = []

    def listen(self, track: rtc.Track) -> None:
        self.tasks.append(asyncio.create_task(self._read(track)))

    async def _read(self, track: rtc.Track) -> None:
        async for ev in rtc.AudioStream(track):
            if _rms(ev.frame) > LOUD_RMS:
                now = time.perf_counter()
                self.last_loud = now
                self.loud_times.append(now)

    def first_loud_after(self, t: float) -> float | None:
        return next((x for x in self.loud_times if x > t), None)

    async def wait_reply(self, after: float) -> float | None:
        """Seconds from `after` to the first loud frame, then wait until the agent is quiet."""
        deadline = after + self.timeout_s
        first = None
        while time.perf_counter() < deadline:
            first = first or self.first_loud_after(after)
            if first and time.perf_counter() - self.last_loud > QUIET_AFTER_S:
                return first - after
            await asyncio.sleep(0.05)
        return None if first is None else first - after


class Mouth:
    """Publishes a microphone track. Sends silence between answers, as a real mic would."""

    def __init__(self, sample_rate: int) -> None:
        self.rate = sample_rate
        self.source = rtc.AudioSource(sample_rate, 1)
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.spoke_until = 0.0
        self.drained = asyncio.Event()
        self.samples = sample_rate * FRAME_MS // 1000
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        silence = b"\x00\x00" * self.samples
        next_at = time.perf_counter()
        while True:
            try:
                data = self.queue.get_nowait()
                speaking = True
            except asyncio.QueueEmpty:
                data, speaking = silence, False
            frame = rtc.AudioFrame(data, self.rate, 1, len(data) // 2)
            await self.source.capture_frame(frame)
            if speaking and self.queue.empty():
                self.spoke_until = time.perf_counter()
                self.drained.set()
            next_at += FRAME_MS / 1000
            await asyncio.sleep(max(0.0, next_at - time.perf_counter()))

    async def say(self, pcm: bytes) -> float:
        step = self.samples * 2
        self.drained.clear()
        for i in range(0, len(pcm) - len(pcm) % step, step):
            self.queue.put_nowait(pcm[i : i + step])
        await self.drained.wait()
        return self.spoke_until

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


async def _render(gw: ModelGateway, text: str) -> bytes:
    return b"".join([chunk async for chunk in gw.synthesize_stream(text)])


async def run_session(
    gw: ModelGateway, answers: list[bytes], rate: int, index: int, timeout_s: float
) -> list[float]:
    settings = get_voice_settings()
    room_name = f"latency-{gw.profile}-{index}-{uuid.uuid4().hex[:4]}"
    room = rtc.Room()
    ear = AgentEar(timeout_s)

    @room.on("track_subscribed")
    def _on_track(track: rtc.Track, *_: object) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            ear.listen(track)

    token = make_token(settings, room_name, f"caller-{index}")
    await room.connect(settings.livekit_url, token)
    mouth = Mouth(rate)
    track = rtc.LocalAudioTrack.create_audio_track("mic", mouth.source)
    opts = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    await room.local_participant.publish_track(track, opts)
    mouth.start()

    results: list[float] = []
    try:
        greeting = await ear.wait_reply(time.perf_counter())
        if greeting is None:
            print(f"  session {index}: no greeting within {timeout_s:.0f} s", flush=True)
            return results
        for n, pcm in enumerate(answers, start=1):
            ended = await mouth.say(pcm)
            took = await ear.wait_reply(ended)
            if took is None:
                print(f"  session {index} turn {n}: no reply", flush=True)
                break
            results.append(took * 1000)
            print(f"  session {index} turn {n}: first reply audio after {took * 1000:.0f} ms")
    finally:
        await mouth.stop()
        for t in ear.tasks:
            t.cancel()
        await room.disconnect()
    return results


async def run(sessions: int, timeout_s: float = DEFAULT_TIMEOUT_S) -> int:
    gw = get_gateway()
    rate = gw.capabilities(Role.TTS).sample_rate or 24000
    answers = [await _render(gw, text) for text in ANSWERS]
    print(f"caller: profile={gw.profile}, {sessions} sessions, {len(answers)} answers each")
    heard: list[float] = []
    for i in range(1, sessions + 1):
        heard += await run_session(gw, answers, rate, i, timeout_s)
        await asyncio.sleep(2.0)  # let the worker close the job and write its CSV rows
    if not heard:
        print("caller: no replies measured")
        return 1
    print(
        f"caller: {len(heard)} turns, end of speech to first reply audio "
        f"p50 {statistics.median(heard):.0f} ms, p95 {percentile(heard, 95):.0f} ms"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sessions", type=int, default=5)
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="seconds to wait for each reply"
    )
    args = parser.parse_args(argv)
    return asyncio.run(run(args.sessions, args.timeout))


if __name__ == "__main__":
    sys.exit(main())
