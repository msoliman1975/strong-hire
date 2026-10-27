# S31 · Coach UI

- **Branch:** `feat/v2-s31-coach-ui`
- **Wave:** 3. **Waits for:** S01 and S21. Use mocks until S30 and S33 merge.
- **Owns:** `apps/web/src/pages/coach/` (new), the takes and versions sections in
  `apps/web/src/pages/stories/` (S21's empty section), `apps/web/src/mocks/coachHandlers.ts` (new),
  and the "build with the coach" links in Home and the plan page.
- **Requirement IDs:** CO-2 (UI), CO-7 (UI), CO-8 (UI).

## Goal

Journey A on screen: a coach conversation with a story taking shape beside it, and takes and
versions on the workbench. Canvas boards: A1 Coach session and A2 Workbench.

## Build

1. `/coach/:sessionId`:
   - conversation on the left, text input, and a mic button that S32 enables
   - "Taking shape" on the right: the five parts filling in, each with its label, plus the
     missing parts and "could prove" tags
   - a style switch (gentle or direct)
   - "Done" saves the story and returns to the workbench
2. Entry points:
   - "Build a story" on Home
   - "missing" rows in the plan's story fit table and the Home coverage map open a coach session
     for that skill
   - "Work on it with the coach" on the workbench
3. Workbench, in S21's empty section:
   - takes, each with its date, channel and per-skill scores; "Record a take" (text now, voice
     after S32)
   - a 60-second and full version toggle with the generated text (CO-8)
4. Show the "practice, not prediction" notice wherever scores show.

## Done when

Web tests cover the CO-2, CO-7 and CO-8 UI against MSW, and the pages work against the real
APIs once S30 and S33 merge.
