# S10 · Interview plan page

- **Branch:** `feat/v2-s10-plan-page`
- **Wave:** 1. **Waits for:** S01, C1.
- **Owns:** `apps/web/src/pages/plan/` (new), `apps/api/src/strong_api/plan/` (new), your route and
  nav lines in the shared hot spots.
- **Requirement IDs:** PP-1, PP-2, PP-4.

## Goal

One page per job and resume pair that replaces the gap analysis, rehearsals (PR-3) and session
setup pages when `v2_enabled` is on. Canvas board: B1 Plan.

## Read first

- `apps/web/src/pages/{GapAnalysisPage,RehearsalPage,SessionSetupPage}.tsx`,
  `apps/web/src/custom/`, `apps/web/src/paths.ts`, `apps/web/src/api/`.
- `apps/api/src/strong_api/{gap,reports,sessions}/` for the data you aggregate.
- Spec: GA-1 to GA-4, PR-2, PR-3, IV-2, IV-4, IV-8, CU-1 to CU-11, JobTarget.interview_date.

## Build

1. API `GET /plan/{job_id}/{resume_id}` returning one `PlanView`: job summary, company mode
   (curated or generic), interview date and days left, what they'll test (profile competency
   weights for the job's types), probe areas (GA-2), the session plan (GA-3), earlier debriefs
   and hire signals (PR-3), the PR-2 recommendation, and the setup defaults. Read-only; reuse
   existing queries rather than copying them. Let the user set the interview date when the job
   has none (PP-2).
2. Web route `/interviews/:jobId/:resumeId` with the plan page: header with countdown, "What
   they'll test", "Where they'll probe", "Earlier rehearsals" and "Next rehearsal".
3. The setup keeps every v1 option (PP-4): type, Custom (reuse the components in
   `apps/web/src/custom/`, do not fork them), difficulty, tone (TN-1 values from C1; S11 makes
   them take effect), mode and duration. Starting a session calls the existing create-session API.
4. Leave empty sections, with a comment, for the story fit table (S23) and readiness (S34). Do
   not build them.
5. With `v2_enabled` on, links to the three old pages go to the plan page. With it off, nothing
   changes. Keep the old pages.

## Done when

API tests cover PP-1 and PP-2; web tests cover PP-1, PP-2 and PP-4 with MSW; a test shows the
flag-off path is unchanged.
