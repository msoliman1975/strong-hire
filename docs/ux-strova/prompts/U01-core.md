# U01 · Core: contracts and migration

- **Branch:** `feat/ux-u01-core`
- **Waits for:** U00.
- **Owns:** `packages/core` (contracts, models, one migration, enums), `schemas/`.
- **Requirement IDs:** SG-1, RH-1 (model), PS-2 (model), RM-2 (model).

## Goal

The small, shared core change that every later task needs. It merges first, alone, as
`CLAUDE.md` requires.

## Read first

`ux-spec.md` sections 7 to 10; `packages/core/src/strong_core/db/models.py` (`User`, `Resume`,
`JobTarget`, `InterviewSession`, `Story`, `USER_OWNED_TABLES`);
`packages/core/src/strong_core/schemas/` (stories, coach, enums); the migration rules in
`CLAUDE.md`; how export and delete (AC-1) list user tables.

## Build

1. Enums: `PlanStyle` (`weekly`, `checklist`); `SuggestionKind` (`tune_story`, `new_story`,
   `missing_skill`, `tailor_role`, `improve_resume_line`, `story_idea`, `review`);
   `SuggestionStatus` (`open`, `accepted`, `dismissed`); `PlanItemKind` (`rehearsal`, `story`,
   `resume`).
2. Models and one Alembic migration (with a working `downgrade()`, enum CHECK constraints created
   once):
   - `users.plan_style` (nullable `PlanStyle`), `users.plan_email_muted` (bool, default false).
   - `resumes.is_main` (bool, default false) plus a partial unique index so a user has at most one
     main among non-deleted resumes. Backfill: each user's newest non-deleted resume becomes main.
   - `target_interviews` (user-owned: `org_id`, `user_id`; `job_target_id`, `resume_id`,
     `interview_type`, `custom_json` nullable, `created_at`, `archived_at`), unique on
     (job_target_id, resume_id, interview_type) where not archived. Backfill one row per distinct
     (job_target_id, resume_id, type) found in existing sessions.
   - `suggestions` (user-owned: `org_id`, `user_id`; `kind`, `status`, `source_session_id`,
     `source_question_ref`, `source_resume_id`, `job_target_id`, `story_id`, `resume_id`,
     `payload` JSON, `reason` text, `prompt_ref`, `undo` JSON, `created_at`, `resolved_at`), index
     on (user_id, status).
   - Add both tables to `USER_OWNED_TABLES`; make sure export and delete cover them.
3. Contracts in `strong_core.schemas` (reject unknown fields): `Suggestion` with one payload model
   per kind (story part edits as `{part, before, after}`; new story parts; target skill; tailoring
   note; resume line `{before, after, resume_line_ref}`; story idea `{achievement, role, skills,
   missing_parts}`; review notes per part); `StoryIdea`; `StoryReview`; `PlanItem` and `Plan`
   (style, items with kind, title, sub, status done/next/todo, due day for weekly, action target);
   `InterviewReadiness` (score 0 to 100 or null, goal 75, per-competency scores, change since last
   take). Add example fixtures for any new output type the gateway will return
   (`gateway/fixtures/coach/<OutputType>.json`) so the fixture validation test covers them.
4. Regenerate `schemas/`.

## Done when

Migration round trip passes in CI, the fixture validation test passes, `USER_OWNED_TABLES` test
passes, and tests named for SG-1, RH-1, PS-2 and RM-2 cover the new columns, tables and contracts.
