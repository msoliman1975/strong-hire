# S23 · Stories in Journey B

- **Branch:** `feat/v2-s23-stories-in-journey-b`
- **Wave:** 2. **Waits for:** S10, S12 and S20. S22 is needed for live data; use mocks until it merges.
- **Owns:** `apps/web/src/pages/plan/StoryFit*`, `apps/web/src/pages/debrief/Story*`, the
  story-fit endpoint added to `apps/api/src/strong_api/plan/` (a new file plus a route line).
- **Requirement IDs:** ST-2 (UI), ST-5 (UI), ST-6 (UI).

## Goal

Stories show up where the candidate preps and where they get feedback. Canvas boards: B1 Plan
and B3 Debrief.

## Read first

- The plan page (S10) and the debrief components (S12). S20's API and S22's story fit function.

## Build

1. Plan page, story fit table (ST-5), in S10's empty section:
   - one row per tested skill: the best story, and a strong, thin or missing mark
   - a missing story links to "New story" (S31 later changes it to a coach session)
2. Debrief (ST-6), in S12's empty section, for each answer:
   - "Story used", linking to the workbench, or "No story matched"
   - the fix with "Sent to story", or "Save as a story" when no story matched (ST-2)
3. A debrief summary card: "N updates for your library", listing the stories that changed.

## Done when

Web tests cover ST-2, ST-5 and ST-6 (UI); the plan endpoint test covers ST-5.
