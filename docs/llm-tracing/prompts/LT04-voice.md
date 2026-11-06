# LT04: Voice turn spans

Read `00-common.md` first.

- **Branch:** `feat/lt-04-voice`
- **Waits for:** LT01
- **Folders:** `apps/voice` (src and tests)
- **Requirement IDs:** LT-3 (voice), LT-6 (voice), LT-7 (voice)

## Build

1. In `strong_voice/agent.py`, where `usage_context(org_id, session_id=...)` is set, also set the
   trace context for a sim user's interview session from `interview_sessions.trace_json`, the
   same way LT03 does (redacted when absent, none for a normal user). The coach agent is out of
   scope.
2. Open a `turn_span("voice", n)` for each interviewer turn, so the STT, interviewer and TTS
   gateway spans of that turn are its children.
3. When the turn's metrics arrive, set `e2e_ms`, `turn_detection_ms`, `stt_ms`, `llm_ttft_ms`,
   `tts_ttfb_ms` and `other_ms` on the span. Reuse the computation in `strong_voice/latency.py`
   (OB-3); do not measure a second way. A missing step stays unset.
4. Nothing here may add latency to the turn (LT-5): span work happens off the audio path.

## Tests

- LT-3: a normal user's voice session makes no span.
- LT-6: with the in-memory fixture, a fake two-turn sim session makes two `turn` spans, each with
  its gateway children and the timing attributes from the same metrics `latency.py` reads.
- LT-7: turn spans carry `service="voice"` and the session tags.

## Done when

- `apps/voice` tests pass, including `test_latency.py` unchanged.
