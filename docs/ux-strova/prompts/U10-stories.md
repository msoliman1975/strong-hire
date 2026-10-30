# U10 · Career Stories

- **Branch:** `feat/ux-u10-stories`
- **Waits for:** U05, U08.
- **Owns:** `apps/web/src/pages/stories/`, `apps/web/src/pages/coach/`, `apps/api/src/strong_api/stories/`,
  `apps/api/src/strong_api/coach/` (start options), `prompts/coach/ask*`, fixtures.
- **Requirement IDs:** ST-8 to ST-14.
- **Mockup routes:** `#stories` (both collapsible sections closed and open, an idea dismissed),
  `#craft` (in progress and done), `#write`, `#review` (before and after review, edit accepted),
  `#story` (Proven with a suggestion, Ready, a crafted story).

## Goal

Career Stories with Strova and its screens, exactly as the mockups show.

## Build

1. **Ready status (ST-8):** the story API returns `display_status` (`draft`, `ready`, `proven`):
   Proven stays as stored; Ready when all five parts are filled. Use it everywhere a status shows.
2. **Career Stories page (ST-9):** title; Start a new story (Craft with Strova, Write it yourself);
   Stories recommended from your resume (collapsed, header "N ideas · M already a story", Build on
   it, Dismiss, from U04); Ask Strova box; Your stories with skill coverage and the list; Strova
   suggests (collapsed, from U08, place `stories`).
3. **Write it yourself (ST-10):** title and five text areas with the hints; Save as a Draft; Save and
   ask Strova to review (saves, then opens Review).
4. **Review with Strova (ST-11):** `POST /stories/{id}/review` creates a `review` suggestion (U08's
   prompt and contract) and returns per-part notes and before-and-after edits; the screen shows the
   parts, the ask panel, then the result with Strova analysing 72 px, Accept or Skip per edit, and
   missing parts with "Answer with Strova" (opens crafting on this story, continuing at the first
   missing part).
5. **Craft with Strova (ST-12):** the existing coach session, restyled as the mockup: chat left,
   "Taking shape" right with Strova thinking 72 px (violet hat) and celebrating when Ready; the
   gentle/direct switch. Start options: from a resume idea (the achievement seeds context, the
   first question asks about stakes), from a missing skill (target skill and role), or blank; and
   continue an existing story.
6. **Ask Strova (ST-13):** `POST /stories/ask` with a question; the coach role answers from the
   user's stories and roles (prompt `ask`, fake fixture, only facts from the user's data); the
   answer shows as a coaching card under the box.
7. **Story page (ST-14):** title, status chip and Draft → Ready → Proven steps, skills, Practice a
   take (CO-7) and Review with Strova, open suggestions (place `story`), parts with 60-second and
   full versions (CO-8), Used for (roles and tailoring notes), Where it came from, takes.

## Tests

One test per ID ST-8 to ST-14; existing ST-1 to ST-7 and CO-* tests still pass.

## Done when

Tests pass and every listed route and state passes the fidelity check at 1280 and 390.
