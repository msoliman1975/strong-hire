# S12 · Debrief, Home and the live room

- **Branch:** `feat/v2-s12-debrief-home-room`
- **Wave:** 1. **Waits for:** S01, C1.
- **Owns:** `apps/web/src/pages/DebriefPage.tsx` and `apps/web/src/pages/debrief/` (new),
  `apps/web/src/pages/DashboardPage.tsx` and `apps/web/src/pages/home/` (new),
  `apps/web/src/session/`, and small additions to `apps/api/src/strong_api/scoring/router.py`
  for DB-1 and DB-2.
- **Requirement IDs:** DB-1, DB-2, PP-3, LR-1, AV-1.

## Goal

Rebuild the three screens Journey B passes through on the v2 design. Canvas boards: Home,
B2 Room and B3 Debrief.

## Read first

- The pages above and their tests, `apps/web/src/components/TrendChart.tsx`,
  `apps/web/src/session/avatar/`.
- Spec: FB-1 to FB-3, PR-1, PR-2, IV-7, IV-8, IV-10, IV-11 and QB-4.

## Build

1. Debrief, with `v2_enabled` on:
   - the hire signal, with the previous signal for the same pair and the change (DB-1)
   - "answers that met the bar" (DB-2)
   - each answer with its quote and fix (FB-2)
   - next in the plan (PR-2), the Questions link (QB-4), the realism rating and the practice notice

   Split the page into components under `pages/debrief/`, so S23 and S24 can add sections without
   editing yours. Leave an empty section for "story used" (S23) and for delivery metrics (S24).
2. Home, with the flag on:
   - interview cards (PP-3) with company, role, match score and days left (`CountdownBadge` from S01)
   - the coach line with the PR-2 advice (`CoachLine`)
   - an empty section for the story library (S21)

   With the flag off, Home is today's dashboard.
3. Live room:
   - An answer-length bar (LR-1): time since the current turn started, against a suggested length
     per interview type. Keep the lengths in one constant.
   - Turn the 3D avatar off behind a build-time flag (AV-1) and show the interviewer state
     (listening, thinking, speaking) without it. Keep `session/avatar/` and its tests compiling
     and passing.
4. Give the room the dark styling from the canvas, using S01's tokens.

## Done when

Tests cover each ID; the LiveSessionPage tests still pass with the avatar off; the flag-off
debrief and dashboard are unchanged.
