# LT05: One MLflow run per sim suite, judge assessments

Read `00-common.md` first.

- **Branch:** `feat/lt-05-sim`
- **Waits for:** LT02, LT03
- **Folders:** `apps/sim` (src and tests)
- **Requirement IDs:** LT-8, LT-9, LT-10, LT-13 (client)

## Build

1. **Dependency.** Add `mlflow-skinny` to `apps/sim`, at the same exact version as LT01.
2. **`strong_sim/mlflow_run.py`**, the only MLflow user in the sim:
   - start a run in the `sim` experiment for each suite run, and for each admin sim in `serve`
     (source `admin`, LT-10);
   - params (LT-8): suite, source, model profile, each role's alias and tier, git SHA, scenario
     count;
   - every MLflow call is wrapped so a failure logs once and never stops the run (LT-13).
3. **Sessions.** `AppClient` sends `X-Sim-Run: <run id>` and `X-Sim-Trace-Content` when it creates
   a session: `full` only when the scenario has no `cv_text` and no `job_text` (D-6).
4. **Judge (LT-9).** Run each session's `judge(...)` inside a sim-side trace, with `trace_context`
   from `strong_core.tracing`, tagged with the session. Attach the verdict as one assessment per
   rule: name, value (pass, fail or not_applicable), rationale, and the rubric prompt ref.
5. **Metrics at the end (LT-8).** From the existing report (`report.py`): sessions done and
   failed, cost per session, p50 and p95 turn latency. From the run's traces (search by
   `sim_run_id`): p50 and p95 `llm_ttft_ms` for each role, retries, validation failures, gateway
   errors, and the prompt refs seen for each role (logged as params). Each judge rule's pass rate.
   Log the HTML report and a per-session table as artifacts.

## Tests

Mock the MLflow client; no server.

- LT-8: a fake two-scenario suite makes one run with the listed params and metrics.
- LT-9: each session's judge verdict becomes one assessment per rule, with the rubric ref.
- LT-10: an admin sim makes a run with source `admin` and one scenario.
- LT-13: a client that raises on every call does not fail the suite, and the run folder on disk
  is complete.
- D-6: a scenario with `cv_text` sends `X-Sim-Trace-Content: redacted`.

## Done when

- `sim-run.ps1` with empty MLflow settings behaves exactly as before.
