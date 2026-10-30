# U05 · Onboarding and resume pages

- **Branch:** `feat/ux-u05-onboarding`
- **Waits for:** U03, U04.
- **Owns:** `apps/web/src/pages/onboarding/`, `apps/web/src/pages/ResumesPage.tsx` (or a new
  `pages/resumes/` folder), the first-run routing in `App.tsx` and `WelcomePage`, MSW handlers for
  these screens.
- **Requirement IDs:** ON-1 to ON-6, RM-1, RM-3.
- **Mockup routes:** `#start`, `#reading`, `#cv-ready` (all three cards collapsed and expanded),
  `#resume-check`, `#plan-style` (both choices), `#what-first`, `#cvs`, `#cv`.

## Goal

A new user goes profile → resume → reading → results → (breakdown and issues) → plan style → what
first, exactly as the mockups show. Returning users manage resumes on the two resume pages.

## Read first

`ux-spec.md` sections 6.1 and 6.3; the current onboarding pages and `steps.ts`; the v2 resume check
(`ResumeCheckV2.tsx`) which you can reuse for the breakdown-and-issues screen; U04's endpoints.

## Build

1. Onboarding shell: no rail, top bar with the three steps Profile · Your resume · Plan style.
2. `#start` (ON-1): upload, paste, and the LinkedIn paste link (same text path). Primary "Read my
   resume".
3. `#reading` (ON-2): `<Strova mode="analysing" size={160} />`, polls the extraction task, moves
   on by itself; refusal (IN-7) shows the reason and "Try another file".
4. `#cv-ready` (ON-3): Strova coaching 88 px, three `<details>` cards collapsed by default with the
   real counts, their content, and the links "Open breakdown and issues" and "Open Career Stories",
   "One more question, then you're in.", primary Continue.
5. `#resume-check` (ON-4): breakdown left, issues right with fix and accept actions (reuse the v2
   check's editing), Back and Continue.
6. `#plan-style` (ON-5): the "What your plan covers now" box with real counts and the dashed
   Rehearsals tile; the two choices with the before-role examples; saves `plan_style` (U04);
   button text follows the choice.
7. `#what-first` (ON-6): Strova coaching 72 px, the exact copy, two choices (to Add a target role,
   to Craft with Strova on the strongest idea), the two links.
8. Routing: after AC-3, a user with no resume goes to `#start`; a user with a resume but no
   `plan_style` resumes at plan style. Visiting any v2 app screen without a resume redirects to
   start.
9. `{First name}'s Resumes` (RM-1) and the resume page (RM-3) as in the mockups, with real story
   ideas (Craft with Strova, Not a story), breakdown, issues and, when U08 has merged, resume-line
   suggestions (render the section only when the API returns some; mocks show one).

## Tests

One test per ID: ON-1 (three inputs), ON-2 (polling, success, refusal), ON-3 (collapsed by default,
counts, links), ON-4 (fix and accept), ON-5 (covers-now box, saves style), ON-6 (copy and links),
RM-1 (first-name title, main marked), RM-3 (sections present). Update the existing onboarding and
journey tests that the new order changes.

## Done when

Tests pass and every listed mockup route passes the fidelity check at 1280 and 390, including the
expanded cards.
