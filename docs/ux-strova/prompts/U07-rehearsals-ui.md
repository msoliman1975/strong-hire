# U07 · Target roles, rehearsals, interview page, live room

- **Branch:** `feat/ux-u07-rehearsals-ui`
- **Waits for:** U03, U06.
- **Owns:** new `apps/web/src/pages/roles/` and `apps/web/src/pages/rehearsals/`, the job add
  flow (`NewJobPage`, `ConfirmJobPage` and friends), `apps/web/src/pages/plan/` (retired behind
  redirects), `apps/web/src/session/` (Strova in the live room), routes in `App.tsx`.
- **Requirement IDs:** TG-1, TG-2, TG-4, RH-3, RH-4, SV-6.
- **Mockup routes:** `#roles`, `#add-role` (steps 1, 2, 3), `#role` (Stripe and Shopify samples),
  `#rehearse`, `#interview` (started, not started, settings drawer open), `#live` (listening,
  thinking, speaking).

## Goal

Target roles, adding a role, the role page, the rehearsals list, the interview page and the live
room, exactly as the mockups show, on U06's API.

## Build

1. `#roles` (TG-1): one card per role with date chip, resume, match and one readiness bar per
   interview; Add a target role.
2. `#add-role` (TG-2): one screen, three steps (posting with link or text, IN-1 and IN-6; check
   the role with optional interview date; interviews Strova suggests as checkboxes with the
   "Measured against" line and Use another resume). Create the role makes the interviews (U06)
   and opens the role page. The gap analysis still runs in the background as today.
3. `#role` (TG-4): back link, title, chips, interview cards (each opens its interview),
   What they'll look for (skills, probe areas, must-haves the resume never shows, link to the
   resume), Your stories for this role (story fit ST-5 with tailoring notes when U08 provides them;
   until then the note row is hidden), the dashed context card (IN-4 form in a dialog).
4. `#rehearse` (RH-4): Strova interviewing 72 px, recommended next take hero, all interviews.
5. `#interview` (RH-3): readiness card (or the first-take empty state), skill coverage, next take
   hero with "Strova will act as …", Start / Start the first take / Retake, settings drawer
   (difficulty, mode Realistic/Practice, tone, length with the existing paywall rules), takes list
   linking to debriefs. Starting a take creates the session for this interview and opens the mic
   check and live room as today.
6. Live room (SV-6): replace the interviewer state block with `<Strova size={160} />` in the
   interviewer hat, mode from the existing interviewer state (listening, thinking, speaking), the
   chip "Strova is {state}", and "Strova is acting as {title} at {company}". Keep phases, captions,
   answer length (LR-1), prep (IV-11), pause/hint/redo in Practice mode, End take.
7. Retire the v2 plan page: its routes redirect to the matching role or interview page. Move the
   tests of PP-1, PP-2, PP-4, RD-1 and RD-3 to the screens that now show those things.

## Tests

TG-1, TG-2, TG-4, RH-3, RH-4, SV-6 each have a test; the moved PP and RD tests pass.

## Done when

Tests pass and every listed route and state passes the fidelity check at 1280 and 390.
