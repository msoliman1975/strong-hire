"""Audio for voice sessions: the candidate's mouth (a mic track), its ear, and the recorder.

The recorder keeps two mono 16-bit tracks on one clock: left = what the candidate heard (the
interviewer), right = what the candidate said. save_ogg() writes one stereo Ogg Opus file with
ffmpeg. Only sim sessions are recorded; product sessions store no audio.

Both tracks are continuous streams of 10 ms frames (the mic sends silence between replies), so a
track's length is its clock: the transcript times (SM-6) are sample positions in these tracks.
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

from strong_sim.timing import LOUD_RMS

RATE = 24_000
FRAME_MS = 10
GAP_S = 0.5  # a frame later than this is a real gap (start, reconnect); less is network jitter


def rms(pcm: bytes) -> float:
    samples = array.array("h", pcm)
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class Recorder:
    """Two mono tracks on one clock that starts at start().

    Frames are appended as they come. Wall-clock time is used only to place a track's first
    frame and to fill a real gap (more than GAP_S of missing audio) with silence. Jitter of a
    few frames is not padded: padding it would push the track ahead of real time a little more
    on every late frame, and the transcript times would drift away from the audio.
    """

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
        gap = offset - len(track)
        if gap > 0 and (not track or gap > GAP_S * self.rate * 2):
            track.extend(b"\x00" * gap)
        track.extend(pcm)

    def ms(self, channel: int) -> int:
        """The length of one track in ms: where its next frame will go."""
        return len(self.tracks[channel]) * 500 // self.rate

    def now_ms(self) -> int:
        """Wall-clock ms since start()."""
        return int((time.perf_counter() - self.t0) * 1000) if self.t0 else 0

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
    """Publishes a microphone track. Sends silence between replies, as a real mic would.

    Every frame, silence too, goes to the recorder's right track, so that track keeps time.
    """

    def __init__(self, recorder: Recorder, rate: int = RATE) -> None:
        self.rate = rate
        self.recorder = recorder
        self.source = rtc.AudioSource(rate, 1)
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.samples = rate * FRAME_MS // 1000
        self.drained = asyncio.Event()
        self.speaking = False
        self.span: tuple[int, int] | None = None  # the current reply in the right track, ms
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
            start = self.recorder.ms(1)
            self.recorder.add(1, data)
            if self.speaking:
                self.span = (self.span[0] if self.span else start, self.recorder.ms(1))
                if self.queue.empty():
                    self.drained.set()
            next_at += FRAME_MS / 1000
            await asyncio.sleep(max(0.0, next_at - time.perf_counter()))

    async def say(self, pcm: bytes) -> tuple[int, int] | None:
        """Speak `pcm`. Returns where it sits in the recording (start, end ms), or None."""
        step = self.samples * 2
        pcm = pcm[: len(pcm) - len(pcm) % step]
        if not pcm:
            return None
        self.drained.clear()
        self.span = None
        for i in range(0, len(pcm), step):
            self.queue.put_nowait(pcm[i : i + step])
        await self.drained.wait()
        return self.span

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

    async def wait_quiet(self, since: float, quiet_s: float = 1.2, timeout_s: float = 90.0) -> bool:
        """Wait until the interviewer spoke after `since` and then stayed quiet for quiet_s."""
        deadline = time.perf_counter() + timeout_s
        while time.perf_counter() < deadline:
            spoke = self.last_loud > since
            if spoke and time.perf_counter() - self.last_loud > quiet_s:
                return True
            await asyncio.sleep(0.05)
        return False

    async def aclose(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        for stream in self.streams:
            await stream.aclose()
        self.tasks.clear()
        self.streams.clear()
