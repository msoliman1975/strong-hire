# PT03: Trace deletion job, alert and retention

Read `00-common.md` and `PT-common.md` first.

- **Branch:** `feat/pt-03-worker`
- **Waits for:** PT01
- **Folders:** `apps/worker` (account jobs, retention, alerts), their tests
- **Requirement IDs:** LT-26, LT-27

## Build

1. **`delete_traces(ctx, org_id, scope, requested_at)`**: calls `delete_org_traces`, retried by
   Arq with backoff; on success writes `tracing.traces_deleted` (scope, count) to the audit log.
2. **Alert (LT-26):** a rule in the alert engine (`docs/alerts.md`) that fires when a trace
   deletion request is older than 12 hours and not done. Keep the request state where the alert
   engine can read it (an audit row for the request and one for success is enough).
3. **Retention (LT-27):** a step in `strong_worker.retention` that calls `prune_prod(30, 90)` when
   `LLM_TRACING_PROD` is on.

## Tests

- LT-26: the job deletes, audits the count, raises for Arq to retry on an MLflow error; the alert
  fires for a request older than 12 hours without success, and not before.
- LT-27: retention calls the prune with 30 and 90 days, only with production tracing on.
