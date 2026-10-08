"""Audio for voice sessions: the candidate's mouth (a mic track), its ear, and the recorder.

The recorder keeps two mono 16-bit tracks on one clock: left = what the candidate heard (the
interviewer), right = what the candidate said. save_ogg() writes one stereo Ogg Opus file with
ffmpeg. Only sim sessions are recorded, on the sim server; the main server stores no audio.
"""

from __future__ import annotations

import array
import asyncio
import contextlib
import math
import shutil
import subprocess
import time
import wave
from pathlib import Path

from livekit import rtc

RATE = 24_000
FRAME_MS = 10
LOUD_RMS = 300.0


def rms(pcm: bytes) -> float:
    samples = array.array("h", pcm)
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class Recorder:
    """Two mono tracks placed by wall-clock time since start()."""

    def __init__(self, rate: int = RATE) -> None:
        self.rate = rate
        self.t0 = 0.0
        self.tracks = (bytearray(), bytearray())  # left: heard, right: said

    def start(self) -> None:
        self.t0 = time.perf_counter()

    def add(self, channel: int, pcm: bytes, at: float | None = None) -> None:
        if not self.t0:
            return
        track = self.tracks[channel]
        offset = int(((at or time.perf_counter()) - self.t0) * self.rate) * 2
        if offset > len(track):
            track.extend(b"\x00" * (offset - len(track)))
            track.extend(pcm)
        else:  # overlap or late frame: append, so no audio is lost
            track.extend(pcm)

    def save_wav(self, path: Path) -> None:
        left, right = self.tracks
        n = max(len(left), len(right))
        left = left + b"\x00" * (n - len(left))
        right = right + b"\x00" * (n - len(right))
        a, b = array.array("h", bytes(left)), array.array("h", bytes(right))
        both = array.array("h", bytes(n * 2))
        both[0::2], both[1::2] = a, b
        with wave.open(str(path), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(self.rate)
            w.writeframes(both.tobytes())

    def save_ogg(self, path: Path) -> Path:
        """Stereo Ogg Opus, about 24 kbps per channel. Falls back to WAV without ffmpeg."""
        wav = path.with_suffix(".wav")
        self.save_wav(wav)
        if not shutil.which("ffmpeg"):
            return wav
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libopus",
             "-b:a", "48k", "-ac", "2", str(path)],
            check=True,
        )  # fmt: skip
        wav.unlink()
        return path


class Mouth:
    """Publishes a microphone track. Sends silence between replies, as a real mic would."""

    def __init__(self, recorder: Recorder, rate: int = RATE) -> None:
        self.rate = rate
        self.recorder = recorder
        self.source = rtc.AudioSource(rate, 1)
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.samples = rate * FRAME_MS // 1000
        self.drained = asyncio.Event()
        self.speaking = False
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        silence = b"\x00\x00" * self.samples
        next_at = time.perf_counter()
        while True:
            try:
                data, self.speaking = self.queue.get_nowait(), True
            except asyncio.QueueEmpty:
                data, self.speaking = silence, False
            frame = rtc.AudioFrame(data, self.rate, 1, len(data) // 2)
            await self.source.capture_frame(frame)
            if self.speaking:
                self.recorder.add(1, data)
                if self.queue.empty():
                    self.drained.set()
            next_at += FRAME_MS / 1000
            await asyncio.sleep(max(0.0, next_at - time.perf_counter()))

    async def say(self, pcm: bytes) -> None:
        step = self.samples * 2
        pcm = pcm[: len(pcm) - len(pcm) % step]
        if not pcm:
            return
        self.drained.clear()
        for i in range(0, len(pcm), step):
            self.queue.put_nowait(pcm[i : i + step])
        await self.drained.wait()

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self.source.aclose()


class Ear:
    """Listens to the interviewer's audio: records it and tracks when it was last loud."""

    def __init__(self, recorder: Recorder, rate: int = RATE) -> None:
        self.recorder = recorder
        self.rate = rate
        self.last_loud = 0.0
        self.loud_count = 0
        self.loud_times: list[float] = []
        self.tasks: list[asyncio.Task[None]] = []
        self.streams: list[rtc.AudioStream] = []

    def listen(self, track: rtc.Track) -> None:
        stream = rtc.AudioStream(track, sample_rate=self.rate, num_channels=1)
        self.streams.append(stream)
        self.tasks.append(asyncio.create_task(self._read(stream)))

    async def _read(self, stream: rtc.AudioStream) -> None:
        async for ev in stream:
            pcm = bytes(ev.frame.data)
            self.recorder.add(0, pcm)
            if rms(pcm) > LOUD_RMS:
                self.last_loud = time.perf_counter()
                self.loud_count += 1
                if not self.loud_times or self.last_loud - self.loud_times[-1] > 0.5:
                    self.loud_times.append(self.last_loud)  # start of each burst of speech

    async def wait_quiet(self, since: float, quiet_s: float = 1.2, timeout_s: float = 90.0) -> bool:
        """Wait until the interviewer spoke after `since` and then stayed quiet for quiet_s."""
        deadline = time.perf_counter() + timeout_s
        while time.perf_counter() < deadline:
            spoke = self.last_loud > since
            if spoke and time.perf_counter() - self.last_loud > quiet_s:
                return True
            await asyncio.sleep(0.05)
        return False

    async def wait_first_loud(self, after: float, timeout_s: float = 30.0) -> float | None:
        """Seconds from `after` to the interviewer's first loud frame, or None on timeout."""
        deadline = after + timeout_s
        while time.perf_counter() < deadline:
            if self.last_loud > after:
                return self.first_loud_since(after) - after
            await asyncio.sleep(0.02)
        return None

    def first_loud_since(self, after: float) -> float:
        return next((t for t in self.loud_times if t > after), self.last_loud)

    async def aclose(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        for stream in self.streams:
            await stream.aclose()
        self.tasks.clear()
        self.streams.clear()
