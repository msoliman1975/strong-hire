# UX with Strova: execution plan

One dedicated loop session builds the approved UX (`ux-spec.md`, `reference/mockups.html`)
end to end, unattended, one task at a time. Each task is one branch and one PR into `main`,
merged by GitHub auto-merge when CI is green. The loop driver is `prompts/LOOP.md`; the rules for
every task are `prompts/00-common.md`.

## Tasks, in order

| ID | Task | Branch | Waits for | Main folders | Requirement IDs |
| --- | --- | --- | --- | --- | --- |
| U00 | Spec and package on main | `feat/ux-u00-spec` | nothing | `docs/spec.md`, `docs/ux-strova/` | writes every ID below into the spec |
| U01 | Core: contracts and migration | `feat/ux-u01-core` | U00 | `packages/core`, `schemas/` | SG-1, RH-1, PS-2, RM-2 (model) |
| U02 | Strova component | `feat/ux-u02-strova` | U00 | `apps/web/src/components/strova/` | SV-1 to SV-5 |
| U03 | Shell, navigation and terms | `feat/ux-u03-shell` | U02 | `apps/web/src/components/Layout.tsx`, copy across v2 screens | NV-1 to NV-3, RH-5, SV-7 (app) |
| U04 | Resume API: main resume, rules, story ideas, plan style | `feat/ux-u04-resume-api` | U01 | `apps/api` (inputs, account), `apps/worker` (inputs), `prompts/extractor/` | RM-2, RM-4, RM-5, PS-2 (API) |
| U05 | Onboarding and resume pages | `feat/ux-u05-onboarding` | U03, U04 | `apps/web/src/pages/onboarding/`, resumes pages | ON-1 to ON-6, RM-1, RM-3 |
| U06 | Roles and interviews API, readiness | `feat/ux-u06-interviews-api` | U01 | `apps/api` (plan, inputs), `apps/worker` (gap) | TG-3, RH-1, RH-2 |
| U07 | Target roles, rehearsals, interview page, live room | `feat/ux-u07-rehearsals-ui` | U03, U06 | `apps/web/src/pages/` (roles, interviews, plan), `apps/web/src/session/` | TG-1, TG-2, TG-4, RH-3, RH-4, SV-6 |
| U08 | Suggestions engine | `feat/ux-u08-suggestions` | U01, U04 | `apps/worker/src/strong_worker/suggestions/`, `apps/api/src/strong_api/suggestions/`, `prompts/coach/`, `evals/` | SG-2 to SG-8 (engine) |
| U09 | Debrief | `feat/ux-u09-debrief` | U07, U08 | `apps/web/src/pages/debrief/` | DB-3 to DB-6, SG-8 (UI) |
| U10 | Career Stories | `feat/ux-u10-stories` | U05, U08 | `apps/web/src/pages/stories/`, `apps/web/src/pages/coach/`, `apps/api` (stories, coach) | ST-8 to ST-14 |
| U11 | Personal plan, Home, Profile, reminders | `feat/ux-u11-plan-home` | U07, U10 | `apps/api` (plan), `apps/worker` (reminders), `apps/web/src/pages/home/`, profile | PS-1 to PS-6, HO-1 |
| U12 | Strova on the site and in emails | `feat/ux-u12-site-email` | U02, U11 | `apps/site/`, email templates and sender names | SV-7 (site), SV-8, SV-9 |
| U13 | End-to-end, fidelity audit, cleanup | `feat/ux-u13-e2e` | all | `apps/web/e2e/`, tests, dead v2 code | the launch check |

Tasks run strictly in this order. A task starts only when every task in its "Waits for" column
has merged into `main`. If a task is blocked, the loop may start the next task whose
dependencies are all merged (for example U06 while U05 is blocked).

## Why one task per PR

`CLAUDE.md` requires that `packages/core` changes merge first in their own small PR, that every
PR has green CI, and that tests stay green on every commit. One task per PR, in this order, keeps
all three rules without anyone merging by hand.

## Done

The build is done when U13 has merged and its report (the PR description) lists every
requirement ID above with the test that covers it, and every mockup screen with its fidelity check.
