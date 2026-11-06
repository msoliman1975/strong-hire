# LT06: End-to-end check and report

Read `00-common.md` first.

- **Branch:** `feat/lt-06-e2e`
- **Waits for:** LT01 to LT05
- **Folders:** tests in any app, `docs/llm-tracing/`, `docs/hosting.md`
- **Requirement IDs:** verifies LT-1 to LT-15

## Build

1. A test map: for each of LT-1 to LT-15, the test that covers it. Add a test for any ID with
   none.
2. One integration test, all fake, no network: a sim user's text session through the API, its
   scoring job and its judge call, with the in-memory exporter. Check the trace tree, the tags,
   the redaction mode, and that a normal user's session in the same test makes no span.
3. If the main server is reachable and the owner has turned `LLM_TRACING=on`: run the
   `text-smoke` suite, open its MLflow run, and record the params, metrics, a turn span and the
   judge assessments in the PR. Run one voice sim and record MLflow's memory (`docker stats`) in
   `docs/hosting.md`. If not reachable, list these as the owner's steps in the PR.
4. Add a short "How to compare two prompt versions" section to `docs/llm-tracing/spec.md`: run
   the same suite twice, then use MLflow's compare view.

## Done when

- The PR description has the full LT-1 to LT-15 test map and the results above.
