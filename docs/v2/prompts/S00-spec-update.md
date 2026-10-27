# S00 · Spec update for v2

- **Branch:** `feat/v2-s00-spec`
- **Wave:** 0. **Waits for:** nothing.
- **Owns:** `docs/spec.md`, `docs/v2/`.
- **Requirement IDs:** writes all v2 IDs into the spec.

## Goal

Make `docs/spec.md` describe v2.0, so every v2 requirement ID is an acceptance test in the spec.

## Read first

- `docs/spec.md` (all of it), `docs/custom-interview-spec.md`, `docs/admin-spec.md`.
- `docs/v2/execution-plan.md`, section "Requirement IDs".
- The v2 plan doc (link in `00-common.md`).

## Build

1. Add a "v2.0" column or section to Scope that lists what moves from "Later releases" into v2.0
   (transcript view, delivery metrics, story bank as the story library, auto-profiles, recruiter
   screen) and what stays later (photo-real avatar, panel, native apps, B2B, languages,
   community reports). Model answers stay out (QB-2).
2. Add the v2 requirement tables from the execution plan to "Functional requirements", grouped
   by part, with priorities: SR-1 is P1, everything else P0.
3. Update the sections the decisions change:
   - Interviewer and scoring design: tone is a user choice with the profile as default (TN-1 to TN-3).
   - Scope, Modality: the 3D avatar is off behind a flag (AV-1).
   - Data model: add Story, CoachSession, CoachTurn, Take, CompanyAutoProfile and the new
     Session and Scorecard fields. Mark them "v2".
   - User journeys: add Journey A (build your stories) and rewrite journey 2 around the plan page.
   - Metrics: add the v2 targets from the plan doc.
4. Keep the v1 text accurate for what v1 does today. Do not delete v1 requirements; mark replaced
   pages (gap analysis page, rehearsals page, session setup page) as "replaced by PP-1 in v2".
5. If any execution-plan ID turns out to clash with an existing ID, rename it in both the spec and
   `docs/v2/execution-plan.md`, and list the rename in the PR description.

## Done when

The PR is docs only, lists every ID added, and passes CI.
