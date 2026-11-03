# RS05 · Check page: stories, lines, drawers; retire the detail page

- **Branch:** `feat/rs-05-check-absorb`
- **Waits for:** RS04.
- **Owns:** `apps/web/src/pages/onboarding/` (the check steps and a new `check/Drawer.tsx`),
  `apps/web/src/pages/resumes/` (remove `ResumeDetailPage.tsx`, keep `IssueList.tsx` only if
  something still uses it), `apps/web/src/App.tsx` (the route), and resume links in
  `apps/web/src/pages/` (Home, WhatFirst, RolePage).
- **Requirement IDs:** RS-6, RS-11, RS-12, RS-14.

## Goal

Everything the detail page did now lives on the check page, and there is one resume page.

## Read first

- Spec: the gap report, RS-6, RS-11, RS-12, RS-14 and D-1.
- The mockup board "Check C2". Click steps 3 and 4 and the three drawer links.
- `ResumeDetailPage.tsx` (story ideas, `ResumeLineSuggestions`, `ResumeLineCard`, `craftFromIdeaPath`,
  `ideaCounts`) and its tests in `pages/start/start.test.tsx` (RM-3, RM-4, SG-6).

## Build

1. **Stories (RS-11):** move the idea logic from `ResumeDetailPage` into `check/StoriesStep.tsx`:
   - one idea at a time, previous and next;
   - skills chips, "Still needs";
   - **Craft with Strova** (`craftFromIdeaPath`) and **Not a story** (`dismissIdea`);
   - "Already crafted · {n}", linking each story with `storyPath`.

   Keep `craftFromIdeaPath` exported from its new home and update its importers.
2. **Lines (RS-12):** move `ResumeLineCard` into `check/LinesStep.tsx`, one at a time, with the
   source story title from the stories list by `story_id`, or the reason when there is none. Add
   to resume, then Undo, and Dismiss. Write the empty copy from RS-12. After Add, refresh the
   draft from the saved resume so step 1 shows the new line.
3. **Drawers (RS-14):** one `Drawer` component:
   - `<dialog>` with `showModal`, a right sheet, at most 460 px and full width under 600 px;
   - a header with the title and a close button;
   - Esc and a backdrop click close it, and focus returns to the opener.

   Use it for:
   - **Used by {n} roles**: active roles that use this resume, each with company, title, the
     `dateChip` text and Open (`rolePath`), plus "Add a target role with this resume";
   - **Findings you accepted · {n}**: the reason label and Undo;
   - **What Strova checks**: today's list.

   Wire the header link and the step list footer links from RS04.
4. **Retire the detail page (RS-6):**
   - `/resumes/:resumeId` becomes a redirect component that sends to `resumeCheckPath(id)` and
     keeps the search string;
   - delete `ResumeDetailPage.tsx`;
   - change `resumePath` to return the check path, or replace its callers;
   - update the links in HomeStrova, WhatFirstPage and RolePage;
   - the mock `action_target` keeps `/resumes/{id}`, which proves the redirect.
5. **Tests:**
   - move RM-3, RM-4 and SG-6 from `start.test.tsx` onto the check page;
   - add RS-6 (the redirect keeps the query), RS-11, RS-12 and RS-14 (focus trap, Esc, focus
     return, roles listed).

## Done when

- The RS-6, RS-11, RS-12 and RS-14 tests pass, and RM-3, RM-4 and SG-6 pass on the check page.
- `rg "ResumeDetailPage"` finds nothing in `apps/web/src`.
- The screen check is done at 1280 and 390 for: stories (open, last idea, none, already crafted),
  lines (one, added and Undo, none), each drawer, and the redirect from an old link.
