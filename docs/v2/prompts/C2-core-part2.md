# C2 · Core changes for Part 2

- **Branch:** `feat/v2-c2-core-part2`
- **Wave:** 2. Start it as soon as C1 merges, while wave 1 runs. **Waits for:** C1.
  **Blocks:** S20, S21, S22, S24, S25, C3.
- **Owns:** `packages/core`, `schemas/`.
- **Requirement IDs:** ST-1 (contract), DM-1 (contract).

## Goal

One small shared PR with every contract, model and migration that the story library and
delivery metrics need.

## Read first

- `CLAUDE.md` sections "Contracts and schemas" and "Migration rules".
- `packages/core/src/strong_core/schemas/{scoring,enums}.py`, `packages/core/src/strong_core/library.py`,
  `packages/core/src/strong_core/db/models.py` (`USER_OWNED_TABLES`).
- The A2 Workbench board on the canvas.

## Build

1. The `Story` model and contract:
   - Fields: id, `org_id`, user_id, title, five parts (`context`, `stakes`, `action`, `result`,
     `reflection`, each optional text), skill tags (`Competency` values), status (`draft`,
     `proven`), source (`debrief_answer`, `manual`, `coach`), and the source session and question
     ref when there is one.
   - Also notes (fix notes from debriefs, with session ref and date), created_at and updated_at.
   - Add the table to `USER_OWNED_TABLES`, and to the export and delete helpers if core owns them.
2. A `StoryPart` enum, shared by UI labels and prompts.
3. Story fields on scoring outputs:
   - per-question `story_id` (nullable) and `story_fix` (nullable text) in the per-question
     scorecard contract
   - a `StoryFitItem` contract (competency, story_id or null, strength `strong`, `thin` or
     `missing`, reason) for the planner
4. A `DeliveryMetrics` contract per answer (words per minute, fillers per minute, duration
   seconds) and a place to store it on the scorecard's per-question data.
5. One migration with a working `downgrade()`, `down_revision` = C1's. Regenerate `schemas/`.
   Fixtures for any new `<OutputType>.json`.

## Done when

The migration checks pass (upgrade, check, downgrade, upgrade); there is a test that `stories`
has `org_id`; schema freshness passes.
