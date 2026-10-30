# U11 · Personal plan, Home, Profile, reminders

- **Branch:** `feat/ux-u11-plan-home`
- **Waits for:** U07, U10.
- **Owns:** a new plan module in `apps/api/src/strong_api/plan/` (personal plan), a reminders job
  in `apps/worker/src/strong_worker/`, the reminder email template, `apps/web/src/pages/home/`,
  the v2 Profile page, the debrief's plan line field.
- **Requirement IDs:** PS-1 to PS-6, HO-1.
- **Mockup routes:** `#home` (weekly and checklist; checklist groups closed and one open),
  `#profile`, `#plan-style` (for the before-role examples, already built in U05).

## Goal

One personal plan drives Home, the reminders and the debrief's "next" line.

## Build

1. **Plan API (PS-1, PS-5):** `GET /me/plan` builds items from the current state (spec section 7):
   rehearsal items from interviews below 75 (U06), story items from tested skills without a Ready
   story, started Drafts and resume ideas (U04, U10), resume items from open issues on the main
   resume (U04's server-side check). No rehearsal items before any target role. Each item: kind,
   title, sub-line, status (done, next, todo), action target (interview id, story id or idea,
   resume). Weekly style also returns the week's dates and a day per item (at most one per day,
   Monday to Saturday, items before an interview date first, deterministic). Checklist style
   returns the three groups with done and total counts and a one-line status naming the next item.
   The debrief API's plan line (U08's field) uses the plan's next item.
2. **Home (HO-1):** greeting by time of day with the first name; Strova next step hero (coaching 104
   px, the PR-2 advice sentence, the why line, primary action from the plan's next item, ghost link
   to its role); the plan card in the chosen style (weekly with chip legend and today highlighted,
   PS-4; checklist with three `<details>` groups closed by default showing chip, title, "X of Y
   done", progress bar and status, PS-3); the four summary cards. No suggestion lists on Home.
3. **Profile (PS-2):** plan style (same two choices, full examples), reminders (in the app: on; by
   email: Mute email / Unmute, saving `plan_email_muted`), account summary; billing, export and
   delete stay where they are.
4. **Reminders (PS-6):** a daily Arq cron job: for users with weekly style, `product_email` on and
   `plan_email_muted` off, send at most one email a day ("Strova from Strong Hire") when an item is
   due today or an interview is 3 days away with readiness below 75, using the existing email
   sender and `email_logs`. Respect the user's time zone when set. Fake sender in tests.
5. Retire the old Home v2 sections that the new Home replaces; move their PP-3, PR-2 and ST-4 test
   coverage to the new Home.

## Tests

PS-1 to PS-6 and HO-1 each have a test (plan items per state, before-role rule, weekly days,
checklist groups, style change, email rules including mute and product_email, one email a day).

## Done when

Tests pass and `#home` (both styles, collapsed and expanded) and `#profile` pass the fidelity check
at 1280 and 390.
