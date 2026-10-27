# S34 · Practice readiness and the day plan

- **Branch:** `feat/v2-s34-readiness`
- **Wave:** 3. **Waits for:** C3 and S10.
- **Owns:** `apps/api/src/strong_api/plan/readiness.py` and `day_plan.py` (new files) with their
  route lines, `apps/web/src/pages/plan/Readiness*` and `DayPlan*`, and the readiness badge on
  the Home interview card (a new component that S12's card renders).
- **Requirement IDs:** RD-1, RD-2, RD-3.

## Goal

Candidates see, per skill, how ready their practice shows them to be, and what to do each day
until the interview.

## Read first

- Spec: PR-1 (Realistic only), ProgressSnapshot, GA-3, PR-2, CU-10, PL-6 (dev data excluded).
- The plan doc's decision on readiness, and its risk "Practice readiness is read as a prediction".

## Build

1. Readiness (RD-1), in code with no model call: per tested skill, from that pair's Realistic
   sessions only, recent sessions weighted more. Coach mode, takes and dev-profile sessions never
   count. Return `not_enough_data` below a minimum number of sessions. Document the formula in
   the module docstring.
2. Day plan (RD-2): from today to `interview_date`, one or two items a day: rehearsals (type,
   difficulty, mode) from GA-3 and PR-2, and story work from the story fit gaps. Rebuild it after
   each debrief. With no date, show the next three steps instead.
3. UI: a per-skill readiness view on the plan page (no single headline number unless it sits next
   to the per-skill view), the day plan, and the notice that it is a practice estimate, not a
   prediction, on every screen that shows readiness (RD-3).

## Done when

Unit tests cover the RD-1 inclusion rules, RD-2 with and without a date, and RD-3 notice presence.
