"""One interview, text or voice, from session start to the end of the conversation (P13)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from livekit import rtc

from strong_core.gateway import ModelGateway
from strong_sim.audio import Ear, Mouth, Recorder
from strong_sim.candidate import SILENCE, Candidate
from strong_sim.client import AppClient
from strong_sim.scenarios import Behavior, Scenario
from strong_sim.settings import SimSettings
from strong_sim.timing import align_voice, latencies, speech_spans
from strong_sim.transcript import Line

log = logging.getLogger("strong_sim")

SESSION_TOPIC = "session"
COACH_TOPIC = "coach"
GRACE_MIN = 5  # minutes past the planned length before the harness ends a voice session
RECONNECT_AFTER_S = 15.0


@dataclass
class Conversation:
    lines: list[Line] = field(default_factory=list)
    ended_by_server: bool = False
    stopped_early: bool = False
    audio_path: Path | None = None
    turn_latency_ms: list[float] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    timing: str = "server"  # "audio": the times are positions in audio.ogg (SM-6)


class _Clock:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()

    def ms(self) -> int:
        return int((time.perf_counter() - self.t0) * 1000)


def _interviewer_lines(
    conv: Conversation,
    clock: _Clock,
    turns: list[dict[str, Any]],
    latency_ms: int | None = None,
) -> None:
    """Add the interviewer's lines; the first gets latency_ms (SM-9: the server's reply time)."""
    for t in turns:
        if t["speaker"] != "interviewer":
            continue
        now = clock.ms()
        conv.lines.append(
            Line(
                speaker="interviewer",
                text=t["text"],
                start_ms=now,
                end_ms=now,
                phase=t.get("phase"),
                question_ref=t.get("question_ref"),
                latency_ms=latency_ms,
            )
        )
        latency_ms = None


async def run_text(
    scenario: Scenario,
    client: AppClient,
    candidate: Candidate,
    sid: str,
    settings: SimSettings,
    conv: Conversation | None = None,
) -> Conversation:
    """Fills `conv` as it goes, so the caller keeps the lines when a turn fails."""
    conv, clock = conv if conv is not None else Conversation(), _Clock()
    out = await client.text_open(sid)
    _interviewer_lines(conv, clock, out["turns"])
    turns = 0
    while not out["ended"]:
        if turns >= settings.max_turns:
            conv.stopped_early = True
            conv.notes.append(f"stopped after {turns} candidate turns")
            await client.end(sid)
            return conv
        reply = await candidate.reply(conv.lines)
        start = clock.ms()
        silent = reply == SILENCE
        conv.lines.append(
            Line(
                speaker="candidate",
                text="..." if silent else reply,
                start_ms=start,
                end_ms=start,
                note="silence" if silent else None,
            )
        )
        sent = time.perf_counter()
        out = await client.text_turn(sid, "..." if silent else reply)
        took = (time.perf_counter() - sent) * 1000
        conv.turn_latency_ms.append(took)
        _interviewer_lines(conv, clock, out["turns"], latency_ms=round(took))
        turns += 1
    conv.ended_by_server = True
    return conv


class _Room:
    """One LiveKit connection: the candidate's mic, ear and the session data channel."""

    def __init__(self, recorder: Recorder, said: asyncio.Queue[list[str] | None]) -> None:
        self.room = rtc.Room()
        self.ear = Ear(recorder)
        self.mouth = Mouth(recorder)
        self.said = said
        self.publication: rtc.LocalTrackPublication | None = None

        @self.room.on("track_subscribed")
        def _on_track(track: rtc.Track, *_: object) -> None:
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                self.ear.listen(track)

        @self.room.on("data_received")
        def _on_data(packet: rtc.DataPacket) -> None:
            if packet.topic != SESSION_TOPIC:
                return
            try:
                msg = json.loads(packet.data.decode())
            except ValueError:
                return
            if msg.get("type") == "ended":
                self.said.put_nowait(None)
            elif msg.get("type") == "state" and msg.get("said"):
                self.said.put_nowait([str(x) for x in msg["said"]])

    async def connect(self, url: str, token: str) -> None:
        await self.room.connect(url, token)
        track = rtc.LocalAudioTrack.create_audio_track("mic", self.mouth.source)
        opts = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        self.publication = await self.room.local_participant.publish_track(track, opts)
        self.mouth.start()

    async def send_end(self) -> None:
        payload = json.dumps({"command": "end"}).encode()
        await self.room.local_participant.publish_data(payload, reliable=True, topic=COACH_TOPIC)

    async def close(self) -> None:
        # Close every native object before the room disconnects (see strong_voice.caller).
        if self.room.isconnected() and self.publication is not None:
            await self.room.local_participant.unpublish_track(self.publication.sid)
        await self.mouth.stop()
        await self.ear.aclose()
        await self.room.disconnect()


def _align(conv: Conversation, recorder: Recorder) -> None:
    """SM-6: put the interviewer's lines on the audio clock and measure each reply's latency."""
    try:
        align_voice(conv.lines, speech_spans(bytes(recorder.tracks[0]), recorder.rate))
    except Exception:  # never lose the recording over the times
        log.exception("could not align the transcript with the audio")
        return
    conv.timing = "audio"
    conv.turn_latency_ms = [float(ms) for ms in latencies(conv.lines)]


async def _speech(gateway: ModelGateway, text: str) -> bytes:
    return b"".join([chunk async for chunk in gateway.synthesize_stream(text)])


async def run_voice(
    scenario: Scenario,
    client: AppClient,
    candidate: Candidate,
    sid: str,
    settings: SimSettings,
    gateway: ModelGateway,
    audio_path: Path,
    conv: Conversation | None = None,
) -> Conversation:
    conv, clock = conv if conv is not None else Conversation(), _Clock()
    recorder = Recorder()
    said: asyncio.Queue[list[str] | None] = asyncio.Queue()
    join = await client.voice_join(sid)
    room = _Room(recorder, said)
    recorder.start()
    clock.t0 = recorder.t0  # one clock for notes, captions and the recording
    await room.connect(join["livekit_url"], join["token"])
    deadline = time.perf_counter() + (scenario.duration_min + GRACE_MIN) * 60
    turns = 0
    dropped = False
    try:
        while True:
            left = deadline - time.perf_counter()
            if left <= 0:
                conv.stopped_early = True
                conv.notes.append("the harness ended the session at the time limit")
                await room.send_end()
                break
            try:
                lines = await asyncio.wait_for(said.get(), timeout=min(left, 120))
            except TimeoutError:
                conv.notes.append(f"no interviewer turn for 120 s at {clock.ms() // 1000} s")
                continue
            if lines is None:
                conv.ended_by_server = True
                break
            heard_at = time.perf_counter()
            now = clock.ms()
            for text in lines:
                conv.lines.append(Line(speaker="interviewer", text=text, start_ms=now, end_ms=now))
            turns += 1
            interrupt = scenario.behavior == Behavior.INTERRUPTS and turns % 3 == 0
            if interrupt:
                await asyncio.sleep(1.5)  # start talking while the interviewer still speaks
            else:
                await room.ear.wait_quiet(heard_at)
            reply = await candidate.reply(conv.lines)
            if reply == SILENCE:
                start = recorder.ms(1)
                conv.lines.append(
                    Line(speaker="candidate", text="...", start_ms=start,
                         end_ms=start + int(settings.voice_silence_s * 1000),
                         note=f"silent for {settings.voice_silence_s:.0f} s")
                )  # fmt: skip
                await asyncio.sleep(settings.voice_silence_s)
                continue
            pcm = await _speech(gateway, reply)
            fallback = recorder.ms(1)
            start, end = await room.mouth.say(pcm) or (fallback, fallback)
            conv.lines.append(
                Line(speaker="candidate", text=reply, start_ms=start, end_ms=end,
                     note="interrupted the interviewer" if interrupt else None)
            )  # fmt: skip
            if scenario.behavior == Behavior.DROPS_CONNECTION and not dropped and turns >= 5:
                dropped = True
                conv.notes.append(f"connection dropped at {clock.ms() // 1000} s")
                await room.close()
                await asyncio.sleep(RECONNECT_AFTER_S)
                join = await client.voice_join(sid)
                room = _Room(recorder, said)
                await room.connect(join["livekit_url"], join["token"])
                conv.notes.append(f"reconnected at {clock.ms() // 1000} s")
    finally:
        await room.close()
        _align(conv, recorder)
        conv.audio_path = recorder.save_ogg(audio_path)
    if not conv.ended_by_server:
        await client.end(sid)
    return conv
