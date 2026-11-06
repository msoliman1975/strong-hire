# LLM tracing with MLflow: execution plan

This plan builds phase 1 of LLM tracing (`docs/llm-tracing/spec.md`, LT-1 to LT-15). Each task is
one branch and one PR into `main`, merged when CI is green. The rules for every task are in
`prompts/00-common.md`. Each task has its own prompt file in `prompts/`.

## Tasks, in order

| ID | Task | Branch | Waits for | Main folders | Requirement IDs |
| --- | --- | --- | --- | --- | --- |
| LT00 | Spec and plan on main | `claude/happy-edison-1eo6ob` | nothing | `docs/` | writes LT-1 to LT-16 into `docs/spec.md` |
| LT01 | Core: tracing module, gateway spans, session trace column | `feat/lt-01-core` | LT00 | `packages/core`, `schemas/` | LT-1, LT-2, LT-4, LT-5, LT-11 (command), LT-14 (model), LT-15 |
| LT02 | Infra: MLflow locally and on the main server | `feat/lt-02-infra` | LT00 | `infra/`, `scripts/dev.ps1`, `docs/hosting.md` | LT-11 (dev.ps1), LT-12, LT-13 (compose and env) |
| LT03 | API and worker: sim-only trace context, text turns, jobs | `feat/lt-03-api-worker` | LT01 | `apps/api` (sessions, auth/sim), `apps/worker/src/strong_worker/ops/context.py` | LT-3, LT-6 (text), LT-7, LT-14 (headers) |
| LT04 | Voice: turn spans with latency | `feat/lt-04-voice` | LT01 | `apps/voice` | LT-3 (voice), LT-6 (voice), LT-7 (voice) |
| LT05 | Sim: one MLflow run per suite, judge assessments | `feat/lt-05-sim` | LT02, LT03 | `apps/sim`, `infra/sim/` (env only) | LT-8, LT-9, LT-10, LT-13 (client) |
| LT06 | End-to-end check and report | `feat/lt-06-e2e` | all | tests, `docs/llm-tracing/` | verifies all |

A task starts only when every task in its "Waits for" column has merged into `main`. LT01 and
LT02 can run in parallel, and so can LT03 and LT04.

## Why this order

- `packages/core` is shared, so LT01 merges first in a small PR of its own (`CLAUDE.md`). It
  holds the migration for `interview_sessions.trace_json`, so no other task touches migrations.
- LT02 needs no code from LT01: it only adds the service and its route.
- LT05 needs LT03's headers on the server to tag sessions, and LT02's route for the sim server to
  reach MLflow.

## Done

Phase 1 is done when LT06 has merged and its PR description lists:

- every requirement ID LT-1 to LT-15, with the test that covers it (LT-16 is the phase 2 item);
- one sim suite run on the main server, with a link to its MLflow run, showing the params,
  metrics, turn spans and judge assessments;
- the measured MLflow memory use on the main server under a voice sim;
- every decision taken during the build.
