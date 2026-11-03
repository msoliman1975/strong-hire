# RS04 · Check page: header, steps, journey, findings

- **Branch:** `feat/rs-04-check-steps`
- **Waits for:** RS01.
- **Owns:** `apps/web/src/pages/onboarding/ResumeCheckV2.tsx` and new files beside it
  (`check/StepList.tsx`, `check/JourneyStep.tsx`, `check/FindingsStep.tsx`, `check/CareerStrip.tsx`),
  the `cvc-*` rules in `apps/web/src/styles.css`, and their tests.
- **Requirement IDs:** RS-7, RS-8, RS-9, RS-10, RS-13.

## Goal

The check page has an order of work: your career journey, then Strova's findings, each step in
view and one finding at a time.

## Read first

- Spec RS-7 to RS-10, RS-13, D-5, D-6, D-7 and D-9, and the mockup board "Check C2: Guided,
  revised (v2)". Press Play and click each step.
- All of `ResumeCheckV2.tsx`: the draft and editing state, `fix()`, `IssuesPanel`, `IssueCard`,
  `useAcceptedIssues`, save and `saveThen`, onboarding `Steps`. Also `resumeChecks.ts`,
  `resumeSummary.ts` and `acceptedIssues.ts`.

## Build

1. **Keep the state where it is.** `ResumeCheckV2` still owns the draft, the editors, the checks,
   `accepted` and save. The step components get props and callbacks. Split the file only along
   these step lines; do not change how the checks run.
2. **Header (RS-7):**
   - the name, then the Default chip or **Set as default** (`resumesApi.setMain`);
   - "Added · Last saved · Used by {n} roles", with the roles link left as a button stub that
     RS05 wires to the drawer;
   - **Upload a new version** (to `START`) and today's primary action.

   Onboarding keeps `Steps` and its landing line.
3. **Step list (RS-8):** four buttons with `aria-current="step"`, names, counts, one line each, and
   the direction tags.
   - Steps 3 and 4 render with their counts but open a placeholder view until RS05.
   - In onboarding mode (D-9), steps 3 and 4 are hidden.
   - The step is in `?step=`. Read it with `useSearchParams`, keep `task` and other params, and
     use the default from RS-8.
   - Below 900 px the list stacks above the view.
   - A footer card holds the three drawer links (stubs until RS05).
4. **Journey (RS-9):** a vertical timeline of today's role cards and editors, with the summary
   first and skills, education and certifications as three tiles after the roles.
   - Gaps come from the findings with `gap` set.
   - The gap link selects that finding in step 2.
   - All existing editing and Save work as today, with their tests kept.
5. **Findings (RS-10):** one finding at a time from the open list (high first, then the existing
   order), with "Finding {i} of {n} · {severity}", previous and next.
   - The **Strova recommends** box holds the fix in place: render the target role's editor fields
     for that target (dates, or the achievement), or "Add {skills}" for skills.
   - Accept buttons with reasons; gap practice.
   - "Next findings" rows select a finding.
   - After a fix is saved or a finding accepted, move to the next one.
   - With none open: "Nothing to fix. Your resume reads well." and a link to step 1.
6. **Career strip (RS-13):** segments sized by months, gaps hatched with the warn tokens, the
   current finding's role outlined, `role="img"` with a spoken summary, and "Open and edit".
7. Remove `IssuesPanel` filters and the inline `WhatWeCheck` (it moves to a drawer in RS05; keep
   its content in a component).

## Done when

- The RS-7, RS-8, RS-9, RS-10 and RS-13 tests pass. The IN-3, IN-12, CheckResumePage and
  ResumeCheckV2 tests still pass, updated for the new layout.
- Onboarding (with a `jobId`) still reaches "Continue to your interview plan".
- The screen check is done at 1280 and 390 for: findings (high, low and none), journey (editing a
  role, a gap, adding a role), onboarding fresh, and a blocked save.
