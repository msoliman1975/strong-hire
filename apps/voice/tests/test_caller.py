"""The simulated caller closes its native LiveKit objects, so the process exits with code 0.

Open audio streams and sources stay alive in the livekit FFI runtime until exit. In CI the
runtime then sometimes aborted with "panic in a function that cannot unwind" (exit code 134).
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from typing import Any

import pytest

from strong_voice import caller


class FakeStream:
    """Stands in for rtc.AudioStream: yields nothing until closed."""

    def __init__(self) -> None:
        self.closed = False

    def __aiter__(self) -> FakeStream:
        return self

    async def __anext__(self) -> Any:
        await asyncio.Event().wait()

    async def aclose(self) -> None:
        self.closed = True


class FakeSource:
    def __init__(self, *_: object) -> None:
        self.closed = False

    async def capture_frame(self, _frame: object) -> None:
        return None

    async def aclose(self) -> None:
        self.closed = True


async def test_ear_aclose_stops_readers_and_closes_streams() -> None:
    ear = caller.AgentEar()
    streams = [FakeStream(), FakeStream()]
    for s in streams:
        ear.streams.append(s)  # type: ignore[arg-type]
        ear.tasks.append(asyncio.create_task(ear._read(s)))  # type: ignore[arg-type]
    tasks = list(ear.tasks)
    await asyncio.sleep(0)

    await ear.aclose()

    assert all(s.closed for s in streams)
    assert all(t.done() for t in tasks)
    assert ear.tasks == [] and ear.streams == []


async def test_mouth_stop_closes_the_audio_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(caller.rtc, "AudioSource", FakeSource)
    monkeypatch.setattr(caller.rtc, "AudioFrame", lambda *a: a)
    mouth = caller.Mouth(24000)
    mouth.start()
    await asyncio.sleep(0.02)

    await mouth.stop()

    assert mouth.source.closed  # type: ignore[attr-defined]


def test_caller_does_not_load_the_agent_stack() -> None:
    """The caller needs livekit.rtc only. livekit.agents also loads onnxruntime and models."""
    code = "import sys, strong_voice.caller; print('livekit.agents' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
