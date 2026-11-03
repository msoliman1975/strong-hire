# RS06 · Journey, accessibility, report

- **Branch:** `feat/rs-06-e2e`
- **Waits for:** RS02, RS03, RS05.
- **Owns:** `apps/web/e2e/` (a new `resume-screens.spec.ts`) and any test fixes.
- **Requirement IDs:** RSD-15; verifies RSD-1 to RSD-16.

## Goal

One end-to-end journey proves the three screens work together on the mocks, and the final report
shows every requirement covered.

## Build

1. A Playwright spec on the mock app, with v2 on, as `strova.spec.ts` does:
   1. Open Resumes and check the three tiles and the ▲ on the default resume.
   2. Rename a resume, then Set as default on another.
   3. Show details lands on the check page, on the findings step.
   4. Fix the gap in place: the count drops and the next finding shows.
   5. Accept a finding with a reason, then Undo it from the accepted drawer.
   6. Open the journey from the strip and edit an achievement. Save.
   7. Stories: Not a story, then Craft with Strova reaches the coach start.
   8. Lines: Add to resume, then Undo.
   9. Open the roles drawer, go to a role, and come back with the browser.
   10. Visit an old `/resumes/{id}` link: it lands on the check page.
   11. Target roles: tiles and Show details.
2. Run axe on Resumes, Target roles and each check step and drawer, at 1280 and 390, with no
   violations and no horizontal scroll (RSD-15).
3. In the PR description, write the final report:
   - every RSD ID with its test;
   - every RS PR with its link;
   - every decision taken across the build;
   - follow-ups (for example RSD-16 if it stayed as it is).

## Done when

- The journey and the axe checks pass in CI.
- The report lists RSD-1 to RSD-16, each with a test.
