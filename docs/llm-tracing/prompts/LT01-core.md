# LT01: Core tracing module, gateway spans, session trace column

Read `00-common.md` first.

- **Branch:** `feat/lt-01-core`
- **Waits for:** LT00
- **Folders:** `packages/core` (src, tests, migrations), `schemas/`, the root `pyproject.toml` and
  `uv.lock` for the new dependency
- **Requirement IDs:** LT-1, LT-2, LT-4, LT-5, LT-11 (the prune command), LT-14 (column and
  contract), LT-15

This is a shared-package PR. Keep it to what is listed here.

## Build

1. **Dependency.** Add `mlflow-tracing` to `packages/core`, pinned to one exact version at least
   two weeks old. Write the version in the PR; LT02 and LT05 use the same one.
2. **`strong_core.tracing`** (design: "Core: `strong_core.tracing`" in the spec):
   - settings: `LLM_TRACING`, `LLM_TRACING_DEV`, `MLFLOW_TRACKING_URI`, `MLFLOW_EXPERIMENT`, and
     the tracking username and password (secret type), through the existing settings pattern;
   - `is_active()`: on, a URI set, and `MODEL_PROFILE != fake` (LT-1). When it is false, import
     MLflow lazily or not at all;
   - `TraceTags` and `trace_context(...)`, a context variable like `usage_context`;
   - `gateway_span(role, alias, tier, ...)` and `turn_span(kind, index)`, with the attributes in
     LT-2 and LT-6;
   - redaction: with `content != "full"`, inputs and outputs become `{"sha256": ..., "len": ...}`
     for each message (LT-4);
   - asynchronous, batched export; tracing errors are caught and logged at most once a minute
     (LT-5);
   - `python -m strong_core.tracing prune --experiment dev --days 30` (LT-11);
   - `strong_core.tracing.testing`: a pytest fixture that installs an in-memory exporter, turns
     tracing on and returns the finished spans.
3. **Gateway.** In `gateway/client.py`, open a span in `complete`, `stream`, `transcribe`,
   `synthesize` and `synthesize_stream` next to the existing usage reporting (`_report_chat`,
   `_report_speech`). Copy tokens and cost from the same values. Record `ttft_ms` on the first
   stream delta, and whether structured output needed the retry. No change to return values.
4. **Contract and column (LT-14).** Add `SessionTraceSettings` (`sim_run_id: str | None`,
   `scenario: str | None`, `content: Literal["full", "redacted"] = "redacted"`) to
   `strong_core.schemas`, add a nullable `interview_sessions.trace_json` column, write the
   migration with a working `downgrade()`, and regenerate `schemas/`.
5. **Import rule (LT-15).** Extend the gateway-rule test (`packages/core/tests/test_architecture.py`
   and `evals/tests/test_gateway_rule.py`, whichever holds the forbidden-import list) so `mlflow`
   may be imported only under `strong_core/tracing/` and `apps/sim/`.

## Tests

- LT-1: with `MODEL_PROFILE=fake`, or with no URI, a gateway call makes no span and imports no
  MLflow exporter.
- LT-2: with the in-memory fixture and a trace context, `complete` with an output type, `stream`,
  `transcribe` and `synthesize` each make one span with the listed attributes. Span cost equals
  the usage row's cost.
- LT-3 (core half): a call with no trace context makes no span.
- LT-4: a redacted span's attributes and inputs and outputs contain none of the message text; a
  `full` span contains it.
- LT-5: with an unreachable URI (no network: use a closed local port), calls succeed, nothing
  raises, and span bookkeeping is under 2 ms p95 over 200 fake calls.
- LT-11: prune deletes traces older than the cutoff (mock the MLflow client).
- LT-14: the contract rejects unknown fields and bad `content` values; the migration round trip
  works.

## Done when

- Every test above passes with `MODEL_PROFILE=fake` and no network.
- No existing gateway test changed behaviour.
- `schemas/` is regenerated.
