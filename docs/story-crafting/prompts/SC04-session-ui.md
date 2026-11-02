# SC04 · Web: style picker and the crafting session

- **Branch:** `feat/sc-04-session-ui`
- **Waits for:** SC02.
- **Owns:** `apps/web/src/pages/coach/` (start page, session page, CSS),
  `apps/web/src/mocks/` (coach handlers).
- **Requirement IDs:** SC-1 (UI), SC-7, SC-17.

## Goal

Crafting a styled story feels like writing. You pick a style, the session is roomy, and the
organized story fills in live beside the conversation.

## Read first

- Spec: D-1, D-2, D-7 and D-14, and "Technical design → Web".
- `CoachStartPage.tsx`, `CoachSessionPage.tsx` and `coach.css`.
- The v2 Career Stories page and Strova's avatar modes (`docs/ux-strova/ux-spec.md` section 4.4).

## Build

1. **Start:** a STAR or CARL choice, each with a one-line description of its sections and
   Strova's suggestion preselected ("Strova suggests CARL for a conflict story"). The idea and
   target-skill starts (ST-12) keep working.
2. **Session layout:** the conversation gets the wide column; the outline panel is beside it at
   1280 and below it at 390.
   - The panel shows each section, with each slot as a chip that is filled (with its text),
     empty or skipped, and the section in progress highlighted.
   - The Ready state shows when the core slots are filled.
3. **Reply box (SC-17):**
   - it grows with the text up to about half the screen, then scrolls;
   - **Expand** opens a full-width writing view, and Esc returns;
   - "Skip this" and "Move on" quick replies;
   - Enter sends and Shift+Enter adds a line, as today;
   - the mic and Talk instead keep working.
4. **Mocks:** MSW handlers for the styled start and turn, with a scripted outline that fills
   section by section.
5. **Tests:** component tests for the picker, the panel states and the reply box (grows, Expand,
   quick replies).

## Done when

- The tests for SC-1 (UI), SC-7 and SC-17 pass.
- The screen check is done for the start, an empty session, a mid-way session, a skipped slot and
  Ready, at 1280 and 390.
- A classic session still looks and works as before.
