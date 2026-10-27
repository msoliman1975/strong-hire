# v2 build: rules for every session

Read this file first, then your own prompt file. Your prompt file names your ID, branch, owned
folders, dependencies and requirement IDs.

## Sources

- `CLAUDE.md`: repo rules (gateway rule, fake-model rule, contracts, migrations, PRs). They all
  still apply.
- `docs/spec.md`: the v1 spec. After S00 merges it also holds the v2 requirements.
- `docs/v2/execution-plan.md`: the waves, the merge order and the requirement IDs (section
  "Requirement IDs"). Use those IDs even if S00 has not merged yet.
- The v2 plan doc: https://claude.ai/artifact/BSjZFLreXzRgqapKdqz87V (decisions, scope, risks).
- The App UX canvas: https://claude.ai/artifact/VspB7PtbLJzFMkrEjaRrKj, page "App UX". Boards:
  Home, A1 Coach session, A2 Workbench, B1 Plan, B2 Room, B3 Debrief, Spec map. The canvas shows
  layout and copy, not final data. Where it differs from a decision below, the decision wins.

## Decisions already made (do not reopen)

- v2 ships as one release, v2.0, built in three parts. Nothing new is shown to users until launch:
  put new user-facing screens behind the runtime setting `v2_enabled` (added by C1) where they
  would otherwise replace a v1 screen.
- Users pick both tone and difficulty. The company profile's persona tone is the default.
- Practice readiness is computed from Realistic sessions only, shown per skill, labeled as a
  practice estimate.
- The new visual language (Geist, violet action color, teal for interview prep) replaces the
  current Strong Hire system in the app. S01 builds it; everyone else uses its tokens.
- The 3D avatar is turned off behind a flag; its components stay in the code.
- Pricing (coach minutes, free tier) is undecided. Coach sessions record minutes like any session;
  do not change billing rules.

## How to work

1. Start from the latest `main` in your own worktree. Branch: the name in your prompt file.
2. Read the spec sections and code your prompt points to before writing code.
3. Edit only the folders your prompt says you own, plus your own tests. You may read anything.
   If you need a change in a folder you do not own, stop and say so in your PR description, or
   ask the session that owns it. Never edit `packages/core` unless you are C1, C2 or C3.
4. Shared hot spots (route list in `apps/web/src/App.tsx`, nav in `apps/web/src/components/Layout.tsx`,
   `apps/web/src/mocks/handlers.ts`, `apps/api/src/strong_api/main.py` router list): add your lines
   only, keep them together, and rebase before merging. Expect small conflicts here.
5. Front-end streams that need an API that has not merged yet: build against MSW mocks in
   `apps/web/src/mocks/`, typed from the contract in `schemas/`. Replace nothing in the mock
   another stream owns; add your own handler file.
6. Every requirement ID you implement gets at least one test with the ID in its name or docstring.
7. Model calls only through `get_gateway()`; prompts only through `load_prompt`; new replies need a
   fake fixture. No test calls a real model or the network.
8. Done when: `./scripts/dev.ps1 test` and `./scripts/dev.ps1 lint` pass, the PR into `main`
   lists the requirement IDs and the folders touched, and CI is green.
9. End your session with a short report: what merged or is open, what you did not finish, and
   anything another session must do next.
