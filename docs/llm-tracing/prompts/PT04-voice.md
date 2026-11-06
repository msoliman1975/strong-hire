# PT04: Voice turn content

Read `00-common.md` and `PT-common.md` first.

- **Branch:** `feat/pt-04-voice`
- **Waits for:** PT01
- **Folders:** `apps/voice`, its tests
- **Requirement IDs:** LT-21 (voice)

## Build

When a voice turn ends (the latency row is cut), and the session's tags say `turn_content`, call
`record_turn_content` with the candidate's transcript and the interviewer's reply for that turn,
taken from the session's saved turns, scrubbed by the org's scrubber (built once per session).

## Tests

- LT-21: a consenting user's voice turn writes a scrubbed `turn.content` trace matching the turn's
  index; a non-consenting user's writes none; audio is never in a trace.
