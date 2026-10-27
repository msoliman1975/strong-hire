# S21 · Story library UI

- **Branch:** `feat/v2-s21-story-library-ui`
- **Wave:** 2. **Waits for:** S01, C2 and S12 (for the Home section). Use mocks until S20 merges.
- **Owns:** `apps/web/src/pages/stories/` (new), `apps/web/src/pages/home/StoryLibrary*` and
  `apps/web/src/pages/home/SkillCoverage*`, `apps/web/src/mocks/storyHandlers.ts` (new).
- **Requirement IDs:** ST-3, ST-4.

## Goal

Candidates can see, edit and organize their stories. Canvas boards: A2 Workbench and Home.

## Read first

- The A2 Workbench and Home boards. S01's `StoryPartChip`. C2's `Story` contract.
- `apps/web/src/pages/MyQuestionsPage.tsx` (list and edit patterns), `apps/web/src/mocks/`.

## Build

1. `/stories`: the library list with status (Draft or Proven), skill tags, and filters by skill
   and status.
2. `/stories/:id`, the workbench:
   - edit the story part by part, each part with its colored label
   - title
   - skill tags (from the competency list)
   - the fix notes, newest first
   - an empty section on the right for takes and versions (S31)
3. "New story" creates a manual story.
4. Home, with `v2_enabled` on: the story library section and the skill coverage map. Skills come
   from the user's interviews (union of the plan pages' tested skills); each is covered by a
   story, thin (Draft only) or missing. Missing skills link to "New story" for now; S31 changes
   that link to a coach session.
5. All story parts use text labels as well as color.

## Done when

Web tests cover ST-3 and ST-4 against MSW; the pages work against S20's real API once it merges
(switch the base URL, not the components).
