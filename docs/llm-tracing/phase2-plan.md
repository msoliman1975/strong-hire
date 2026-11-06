# LLM tracing phase 2 (production): execution plan

This plan builds phase 2 (`docs/llm-tracing/spec.md`, "Phase 2", LT-16 to LT-31). Each task is one
branch and one PR into `main`, merged when CI is green. The rules for every task are in
`prompts/00-common.md`, plus the phase 2 rules in `prompts/PT-common.md`.

## Tasks, in order

| ID | Task | Branch | Waits for | Main folders | Requirement IDs |
| --- | --- | --- | --- | --- | --- |
| PT00 | Spec, gates and plan on main | `claude/happy-edison-1eo6ob` | nothing | `docs/` | writes LT-16 to LT-31 |
| PT01 | Core: production rule, metadata mode, scrubber, content trace, consent column, deletion helpers | `feat/pt-01-core` | PT00 | `packages/core`, `schemas/` | LT-16, LT-17, LT-18, LT-19 (rule), LT-20 (model), LT-22, LT-23, LT-31 |
| PT02 | API and web: consent toggle, withdrawal and account deletion queue trace deletion, text turn content | `feat/pt-02-api-web` | PT01 | `apps/api` (account, sessions), `apps/web` (account page) | LT-20, LT-21 (text), LT-24, LT-25 |
| PT03 | Worker: `delete_traces` job, 12-hour alert, production retention | `feat/pt-03-worker` | PT01 | `apps/worker` (account, retention, alerts) | LT-26, LT-27 |
| PT04 | Voice: turn content for consenting users | `feat/pt-04-voice` | PT01 | `apps/voice` | LT-21 (voice) |
| PT05 | Access: MLflow behind admin sign-in, view audit, sim token, Controls switch | `feat/pt-05-access` | PT01 | `infra/`, `apps/api/src/strong_api/admin`, `apps/admin`, `docs/hosting.md` | LT-19 (switch), LT-28, LT-29 |
| PT06 | End-to-end check, gates and report | `feat/pt-06-e2e` | all | tests, `docs/llm-tracing/` | LT-30; verifies all |

PT02 to PT05 can run in parallel once PT01 has merged.

## Why this order

- `packages/core` merges first in its own PR (`CLAUDE.md`). PT01 holds the only migration
  (`users.tracing_consent`), so no other task touches migrations.
- Both flags stay off by default in every task, so each PR is safe to merge on its own: nothing
  traces a real user until the owner meets a gate.

## Done

Phase 2 is built when PT06 has merged and its PR description lists every requirement ID LT-16 to
LT-31 with the test that covers it, and the state of each gate in `phase2-gates.md`. It is live
only when the owner meets the gates.
