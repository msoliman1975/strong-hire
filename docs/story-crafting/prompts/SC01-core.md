# SC01 · Core: enums, outline contracts, migration

- **Branch:** `feat/sc-01-core`
- **Waits for:** SC00.
- **Owns:** `packages/core` (enums, contracts, models, one migration, gateway fixtures),
  `schemas/`.
- **Requirement IDs:** SC-1 (model), SC-2 (model).

## Goal

The small, shared core change that every later task needs. It merges first, alone, as `CLAUDE.md`
requires.

## Read first

- Spec: "Sections and slots", D-1 to D-4, and "Technical design → Core".
- `packages/core/src/strong_core/db/models.py`: `Story`, `CoachSession`, `USER_OWNED_TABLES`.
- `packages/core/src/strong_core/schemas/`: `stories.py`, `coach.py`, `enums.py`.
- The migration rules in `CLAUDE.md`.

## Build

1. **Enums** in `strong_core.schemas.enums`:
   - `StoryStyle` (`star`, `carl`);
   - `StorySection` (`situation`, `challenge`, `task`, `action`, `result`, `learning`);
   - `SlotStatus` (`filled`, `empty`, `skipped`);
   - `FlowFlagType` (`action_vs_problem`, `result_vs_problem`, `number_conflict`,
     `timeline_conflict`, `loose_end`).
2. **Contracts** in `strong_core.schemas` (reject unknown fields):
   - `OutlineSlot`: `text`, `quotes`, `by_user`, `status`. A filled slot needs quotes unless it
     is `by_user`.
   - `ActionStep`: `did`, `why`, `alternatives`, `people`, each an `OutlineSlot` or null.
   - `ResultMetric`: `before`, `after`, `unit` and `text`, with quotes.
   - `StoryOutline`: `style`, `sections`. The slot keys must follow the spec table, so add a
     validator that rejects unknown slot keys per style, and `steps` must hold 1 to 5 items.
   - `CraftReply`: `message`; `slot_updates[]` (section, slot or step index, text, quotes);
     `skips[]`; `section_done`; `skills`; `hints[]`.
   - `FlowFlag` (`key`, `type`, `slots`, `question`) and `FlowCheck` (`flags[]`).
   - `SectionImprove`: `edits[]` (slot, before, after, quotes) or `questions[]`, never both empty.
   - `OrganizeResult`: an outline for STAR built from a classic story, with quotes.
   - `StyleRewrite`: the outline in the other style, with quotes.
3. **Models and one Alembic migration**, with a working `downgrade()`; enum CHECK constraints
   are created once, as `CLAUDE.md` says:
   - `stories.style`: nullable `StoryStyle`;
   - `stories.outline_json`: nullable JSONB;
   - `stories.flow_json`: nullable JSONB, the last flow check and the dismissed flag keys;
   - `stories.hints_json`: nullable JSONB, skill hints with their state;
   - `coach_sessions.section`: nullable `StorySection`.

   No backfill: classic stories keep null (D-11).
4. **Fake fixtures**: one example per new output type in
   `gateway/fixtures/coach/<OutputType>.json`, so the fixture validation test covers them.
5. **Regenerate** `schemas/`.

## Done when

- The migration round trip passes in CI.
- The fixture validation test passes.
- Tests named for SC-1 and SC-2 cover the new columns and contracts: a STAR outline and a CARL
  outline validate, and an unknown slot, six steps, or a Strova slot without quotes is rejected.
