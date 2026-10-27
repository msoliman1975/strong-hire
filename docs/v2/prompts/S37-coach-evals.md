# S37 · Coach evals

- **Branch:** `feat/v2-s37-coach-evals`
- **Wave:** 3. **Waits for:** C3. Runs against S30's prompts once they merge.
- **Owns:** `evals/` (coach suites, fixtures and scenarios), coach scenarios in `apps/sim/`.
- **Requirement IDs:** CO-9.

## Goal

Evidence, before launch, that the coach helps without writing the candidate's story for them.

## Read first

- `evals/README.md`, `docs/sim-candidate.md`, `apps/sim/`, `prompts/judge/`.

## Build

1. Simulated candidates for coach sessions: a vague candidate, one who overclaims, one who goes
   off topic, and one with a strong story.
2. Checks:
   - no invented facts: every story part traces to the candidate's turns (CO-9)
   - one question at a time
   - IV-3 coverage
   - style difference between gentle and direct
   - versions are faithful
   Use the judge role where code cannot check.
3. A suite that runs offline on the fake model in CI (structure only), and a full suite you run
   on the hosted profile and report on. Add the pass threshold to the launch gate in the PR.

## Done when

The CI suite runs green, and a first hosted run report is committed under `evals/reports/`.
