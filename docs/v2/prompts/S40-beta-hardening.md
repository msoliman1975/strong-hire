# S40 · Closed beta and the launch gate

- **Branch:** `feat/v2-s40-beta`
- **Wave:** 4. **Waits for:** all of wave 3 merged (S36 may be closed without merging).
- **Owns:** end-to-end tests across the repo, `infra/` changes for the beta, `docs/v2/beta.md` (new).
- **Requirement IDs:** the launch gate in the v2 plan doc.

## Goal

Prove v2 works end to end with real users, and decide whether it launches.

## Build

1. End-to-end journey tests on the fake model:
   - Journey A: Home, coach session, story, take, versions
   - Journey B: Home, plan page, rehearsal, debrief, story update, readiness
   - both with `v2_enabled` on, plus a v1 regression run with it off
2. Load test 10 concurrent voice sessions (5 interview, 5 coach) on staging, and record cost per
   session against the spec targets.
3. Re-run the scorer gold set (spec "Calibration"); the scorer must stay within one band on 85%
   or more.
4. `docs/v2/beta.md`: how to invite the closed beta, what to measure, and the gate:
   - realism 4.2 of 5 or more
   - coach evals pass
   - 40% of beta users save a story within 30 days
5. A checklist for turning on `v2_enabled` in production, and a rollback (turn it off).

## Done when

The end-to-end tests are green in CI, and `beta.md` holds the load test, gold set and gate
numbers, with a go or no-go line for the user to sign.
