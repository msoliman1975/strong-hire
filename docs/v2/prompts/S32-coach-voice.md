# S32 · Coach voice

- **Branch:** `feat/v2-s32-coach-voice`
- **Wave:** 3. **Waits for:** S30.
- **Owns:** `apps/voice/src/strong_voice/coach*` (new files), the coach channel switch in
  `apps/web/src/pages/coach/` (coordinate with S31: add a hook file, not page edits).
- **Requirement IDs:** CO-6.

## Goal

Candidates can talk to the coach, and record takes by voice, on the same voice loop as
interviews.

## Read first

- `apps/voice/src/strong_voice/{agent,interview_agent,turns,latency}.py`, IV-1, IV-9.
- S30's coach API.

## Build

1. A coach agent that reuses STT, TTS, turn detection and reconnect from the interview agent, and
   calls S30's coach turn logic instead of the interviewer. No session controller phases; the
   coach session ends when the candidate ends it.
2. Voice takes: record one telling, then send the transcript to S33's take scoring. Audio is
   never stored.
3. Keep interview latency unchanged: the interview agent's code path must not change behavior.
   Run the existing latency test before and after.

## Done when

The voice tests (fake STT and TTS) cover CO-6, and the interview latency test shows no regression.
