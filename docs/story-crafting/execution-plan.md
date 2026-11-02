# Deep story crafting: execution plan

One dedicated loop session builds RMAP-8, deep story crafting (`docs/story-crafting-spec.md`),
end to end and unattended, one task at a time. Each task is one branch and one PR into `main`,
merged by GitHub auto-merge with squash when CI is green. The loop driver is `prompts/LOOP.md`;
the rules for every task are `prompts/00-common.md`.

## Tasks, in order

| ID | Task | Branch | Waits for | Main folders | Requirement IDs |
| --- | --- | --- | --- | --- | --- |
| SC00 | Spec and loop on main | `feat/sc-00-spec` | nothing | `docs/` | writes SC-1 to SC-18 into `docs/spec.md` |
| SC01 | Core: enums, outline contracts, migration | `feat/sc-01-core` | SC00 | `packages/core`, `schemas/` | SC-1, SC-2 (model) |
| SC02 | API: outline engine and the craft turn | `feat/sc-02-engine` | SC01 | `apps/api/src/strong_api/coach`, `stories`, `prompts/coach/`, gateway fixtures | SC-3, SC-4, SC-5, SC-6, SC-14 |
| SC03 | API: edit, improve, organize, switch style | `feat/sc-03-story-api` | SC02 | `apps/api` (stories, coach), `prompts/coach/`, fixtures | SC-10 (API), SC-11, SC-12, SC-13 |
| SC04 | Web: style picker and the crafting session | `feat/sc-04-session-ui` | SC02 | `apps/web/src/pages/coach/`, mocks | SC-1 (UI), SC-7, SC-17 |
| SC05 | Web: the organized story page | `feat/sc-05-story-ui` | SC03, SC04 | `apps/web/src/pages/stories/`, mocks | SC-10, SC-11 (UI), SC-12 (UI), SC-13 (UI) |
| SC06 | Flow check and skill hints | `feat/sc-06-flow-hints` | SC05 | `apps/api` (coach, stories), `prompts/coach/`, `apps/web` (coach, stories) | SC-8, SC-9 |
| SC07 | Formatting and the voice light flow | `feat/sc-07-format-voice` | SC06 | `apps/web` (editor components), `apps/api` (renderer), `apps/voice` (coach flow) | SC-16, SC-18 |
| SC08 | Evals, end-to-end, report | `feat/sc-08-e2e` | all | `evals/`, `apps/web/e2e/`, tests | SC-15; verifies all |

Tasks run strictly in this order. A task starts only when every task in its "Waits for" column has
merged into `main`. If a task is blocked, the loop may start the next task whose dependencies are
all merged: for example SC04 while SC03 is blocked, since both wait only for SC02.

## Why one task per PR

`CLAUDE.md` requires three things:

- `packages/core` changes merge first, in their own small PR;
- every PR has green CI;
- tests stay green on every commit.

One task per PR, in this order, keeps all three.

## Done

The build is done when SC08 has merged and its report (the PR description) lists:

- every requirement ID SC-1 to SC-18, with the test that covers it;
- every screen checked, with its states;
- every decision taken during the build.
