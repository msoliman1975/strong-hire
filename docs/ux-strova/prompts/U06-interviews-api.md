# U06 · Roles and interviews API, readiness

- **Branch:** `feat/ux-u06-interviews-api`
- **Waits for:** U01.
- **Owns:** `apps/api/src/strong_api/plan/` (new files for interviews and readiness; the old plan
  page endpoints stay until U12), the job target routes in `apps/api/src/strong_api/inputs/`, the
  sessions create path (to link a session to its interview), MSW handlers for these endpoints.
- **Requirement IDs:** TG-3, RH-1, RH-2.

## Goal

The server side of target roles, interviews and readiness per interview.

## Read first

`ux-spec.md` sections 6.4, 6.5 and 9; `apps/api/src/strong_api/plan/` (service, readiness, story
fit, day plan); company profile rounds and weights (`strong_core.profiles`); the session create
route; RD-1's readiness code.

## Build

1. **Suggested interview types (TG-3):** `GET /roles/{job_target_id}/suggested-interviews`
   returns the company's rounds from the profile loop (standard loop in generic mode: behavioral,
   hiring manager, technical Q&A), each with a one-line description and `usual` true or false.
2. **Interviews (RH-1):** create, list and archive `target_interviews` for a role
   (`POST /roles/{id}/interviews` with the kept types; adding Custom takes the existing custom
   config). Creating a role through the add flow creates its interviews in the same request. Each
   interview has an id used by the web routes (`/interviews/{interview_id}`).
3. **Sessions link to interviews:** creating a take for an interview sets type, job target and
   resume from it. Existing sessions map to their interview by (job_target_id, resume_id, type).
4. **Readiness (RH-2):** per interview, the formula in spec section 9, from Realistic takes only,
   goal 75, per-competency scores, change since the previous take, and the takes list (number,
   mode, date, met-the-bar count, hire signal, session id). `GET /interviews/{id}` returns the
   interview, its role summary, readiness and takes; `GET /roles` returns each role with its
   interviews' readiness; `GET /rehearsals` returns every interview across roles and the
   recommended next take (closest interview date first, then lowest readiness below 75).
5. Interviewer title for "acting as" (spec section 4.1): computed on the server from the profile
   or the type table, returned with the interview.

## Tests

TG-3 (curated and generic suggestions), RH-1 (create with role, archive, unique, session linking
and backfill mapping), RH-2 (formula, Realistic only, no score without a take, change since last).

## Done when

Tests pass, OpenAPI types regenerated, MSW handlers return the mockup's sample shapes.
