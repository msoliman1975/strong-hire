# U08 · Suggestions engine

- **Branch:** `feat/ux-u08-suggestions`
- **Waits for:** U01, U04.
- **Owns:** new `apps/worker/src/strong_worker/suggestions/`, new
  `apps/api/src/strong_api/suggestions/`, `prompts/coach/suggest_*` and `prompts/coach/review*`,
  their fake fixtures, `evals/` (coach suites), one call each in the scoring pipeline and the story
  fit job.
- **Requirement IDs:** SG-2 to SG-8 (engine and API).

## Goal

Strova's suggestions are created by the right events, stored, listed where they belong, and
applied or dismissed safely.

## Read first

`ux-spec.md` section 8; the scoring pipeline and ST-6 story matching
(`apps/worker/src/strong_worker/scoring/stories.py`); story fit (`gap/story_fit` and the plan
endpoint); the coach engine and its CO-9 eval suite; U01's `Suggestion` contracts.

## Build

1. **API:** `GET /suggestions?place=debrief&session_id=…|story&story_id=…|role&job_target_id=…|
   stories|resume&resume_id=…` (open ones, newest first); `POST /suggestions/{id}/accept`
   (optionally with an edited `after` text for "Edit first"); `POST /suggestions/{id}/dismiss`;
   `POST /suggestions/{id}/undo` for an accepted edit (restores the stored `undo` data).
   Accepting applies the change: story part edit, new story saved (Draft or Ready), tailoring note
   added to the story's notes for that role, resume line updated (then the rule check re-runs),
   missing skill returns the crafting target. Dismissed never comes back (same kind, source and
   target).
2. **Worker generation** (gateway role `coach`, prompts via `load_prompt`, fake fixtures):
   - after scoring a take: `tune_story` for each answer that used a story and has a fix, with a
     before-and-after of one part using only words from the answer (SG-2); `new_story` for an
     answer that scored 4, or 3 with all parts present, and matched no story (SG-3);
     `missing_skill` for a tested skill with no story or an answer scored 2 or less (rule-based,
     SG-4);
   - after story fit for a role: `tailor_role` notes (SG-5);
   - after a story gains a result with a number: `improve_resume_line` when its source resume
     line lacks it (SG-6);
   - `review` on request from U10's endpoint (shared prompt and contract here).
3. **No new facts (SG-7):** extend the CO-9 eval suite to tune, new story, review and improve
   resume line (fixtures that try to add facts must be rejected by the check).
4. Debrief data: the scoring router's debrief response includes the open suggestions for the
   session, and the "next plan item" text once U11 exists (leave a nullable field now).

## Tests

SG-2 to SG-6 (each created by its event with fake fixtures; accept applies it), SG-7 (eval passes on
good fixtures, fails on a fact-adding fixture), SG-8 (accept, dismiss, undo, no return after
dismiss), plus export and delete cover suggestions.

## Done when

Tests pass, MSW handlers return sample suggestions of every kind, OpenAPI types regenerated.
