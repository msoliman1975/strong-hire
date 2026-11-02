# SC08 · Evals, end-to-end, report

- **Branch:** `feat/sc-08-e2e`
- **Waits for:** every other task.
- **Owns:** `evals/` (story crafting suites), `apps/web/e2e/`, cross-cutting test updates.
- **Requirement IDs:** SC-15; verifies all of SC-1 to SC-18.

## Goal

Prove that deep crafting works end to end and never adds a fact, then report.

## Build

1. **No-new-facts eval (SC-15):** extend the CO-9 and SG-7 suite to crafting turns, improve,
   organize and rewrite. It checks facts, not wording: every number, proper noun, tool and result
   claim in Strova's text must appear in the user's words. Fixtures include tempting cases, such
   as a user who gives a range or says "about".
2. **Depth suite:** scripted sessions check that every context slot is asked once, a skipped slot
   is never asked again, and "move on" ends a section.
3. **Flow suite:** seeded incoherent stories check that each flag type is found and a coherent
   story gets no flags.
4. **Playwright journey** in mock mode with `v2_enabled`, with axe on each screen:
   - pick CARL;
   - craft section by section with one skip;
   - Ready;
   - a hint, then Not now;
   - a flow flag, then Dismiss;
   - the story page: an inline edit, Improve with Accept, Switch to STAR;
   - a classic story, Organize, Accept.

   Keep the existing journeys passing.
5. **Report** (the PR description): every requirement ID SC-1 to SC-18 with its test, every screen
   checked, the follow-ups, and all decisions logged during the build. Also mark RMAP-7 and RMAP-8
   Done in `docs/roadmap.md`.

## Done when

The evals and the journey pass in CI, the full checks pass, and the report is complete.
