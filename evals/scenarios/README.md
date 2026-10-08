# Sim suites (P13)

Each file is one suite for the AI candidate (`apps/sim`). Run one with
`infra/sim/sim-run.ps1 -Suite <name>` from your machine, or `strong-sim run --suite <name>` on the
sim server. `strong-sim plan --suite <name>` lists the scenarios and the cost estimate.

Fields per scenario (defaults in `strong_sim.scenarios.Scenario`): `id`, `channel` (text,
voice), `interview_type`, `difficulty`, `mode`, `duration_min` (10, 30, 45), `resume` (a fixture
in `evals/fixtures/inputs/resumes`), `quality` (strong, average, weak), `behavior` (see
`prompts/candidate/behavior_*.v1.txt`). `interrupts` and `drops_connection` need voice.

A `pairwise:` block generates scenarios so that every pair of values appears at least once.
The scorer order check compares scenarios that differ only in `quality`.
