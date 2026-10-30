# U04 · Resume API: main resume, rules, story ideas, plan style

- **Branch:** `feat/ux-u04-resume-api`
- **Waits for:** U01.
- **Owns:** `apps/api/src/strong_api/inputs/` (resume routes), `apps/api/src/strong_api/account/`
  (profile fields), a new `apps/api/src/strong_api/resume_checks/`, `apps/worker/src/strong_worker/inputs/`
  (story idea skills job), `prompts/extractor/story_idea_skills*`, their fixtures, shared check
  fixtures.
- **Requirement IDs:** RM-2, RM-4, RM-5, PS-2 (API).

## Goal

Everything the onboarding and resume screens need from the server.

## Read first

`ux-spec.md` sections 6.1, 6.3, 8 (story idea); the web rule-based check
`apps/web/src/pages/onboarding/resumeChecks.ts` and its tests; `acceptedIssues.ts`; the resume
routes and the extraction task in `apps/api/src/strong_api/inputs/` and the worker.

## Build

1. **Main resume (RM-2):** the first resume a user adds becomes main; `POST /resumes/{id}/main`
   sets another; deleting the main makes the newest other one main. Resume list and detail return
   `is_main`. New roles default to the main resume.
2. **Rule-based check in the API (RM-5):** port `resumeChecks.ts` to Python with identical rules
   and messages. Move its test cases into shared JSON fixtures (for example
   `packages/core/tests/fixtures/resume_checks/*.json`, or another shared path both apps can read)
   and run them from pytest and from Vitest so both implementations stay identical.
   `GET /resumes/{id}/issues` returns open and accepted issues (accepted issues as stored today),
   with the job-mode check (must-haves the resume never shows) when `job_target_id` is given.
3. **Story ideas (RM-4):** `GET /resumes/{id}/story-ideas` lists one idea per achievement in the
   parsed resume that no story uses (match by `Story.source` and stored achievement text), with
   the role it belongs to and `missing_parts` (stakes and reflection at least; also action when the
   line has no verb in the first person past tense, keep it simple and rule-based). Ideas the user
   dismissed are stored as `story_idea` suggestions with status `dismissed` and are not listed.
   `POST /resumes/{id}/story-ideas/dismiss` with the achievement reference. Likely skills come from
   one worker job per resume, run after extraction (gateway role `extractor`, prompt
   `story_idea_skills`, output a list of competencies per achievement, fake fixture); until it
   finishes, or if it fails, ideas list without skills.
4. **Plan style and email mute (PS-2):** add `plan_style` and `plan_email_muted` to the profile
   GET and PATCH (`/account/profile` or wherever AC-3 lives).
5. Export and delete include anything new.

## Tests

RM-2 (first resume main, switch, delete fallback, default for new roles), RM-4 (ideas exclude used
achievements and dismissed ones, skills attached after the job, list without skills on failure),
RM-5 (shared fixtures pass in Python and in Vitest), PS-2 (profile round trip).

## Done when

Tests pass, MSW handlers exist for the new endpoints, and OpenAPI types are regenerated for the web.
