# S36 · Story radar (optional)

- **Branch:** `feat/v2-s36-story-radar`
- **Wave:** 3. **Waits for:** S32 and a passing latency test (step 1). This is the first item to
  cut if the June date is at risk.
- **Owns:** `apps/voice/src/strong_voice/radar*` (new), `apps/web/src/session/StoryRadar*` (new),
  and one render line in the live room.
- **Requirement IDs:** SR-1.

## Goal

In Coach mode, the live room shows which story the candidate is telling and which parts they
have covered. Canvas board: B2 Room.

## Build

1. Spike first: a radar that runs on the caption stream, outside the interviewer's turn path
   (its own task, with no await in the interviewer loop). It matches the answer to a story and
   marks the parts covered, using the extractor role with a small prompt, at most once every few
   seconds.
2. Measure p50 and p95 voice latency with and without it (the existing latency harness, hosted
   profile). If p95 rises at all, stop, report the numbers, and do not merge the feature. That
   result counts as done.
3. If it passes: show the radar only in Coach mode, behind a runtime setting that is off by
   default.

## Done when

The PR carries the latency numbers. Either the feature merges with tests for SR-1, or a report
closes the item.
