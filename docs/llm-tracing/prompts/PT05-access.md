# PT05: MLflow behind admin sign-in

Read `00-common.md` and `PT-common.md` first.

- **Branch:** `feat/pt-05-access`
- **Waits for:** PT01
- **Folders:** `infra/` (Caddy, compose, mlflow start), `apps/api/src/strong_api/admin`,
  `apps/admin` (Controls page), `docs/hosting.md`, their tests
- **Requirement IDs:** LT-19 (switch), LT-28, LT-29

## Build

1. **MLflow under the admin host (LT-28):** start the server with `--static-prefix /mlflow`;
   Caddy's `admin.{$DOMAIN}` site proxies `/mlflow/*` to it after `forward_auth` to
   `GET /admin/mlflow-auth`, which returns 200 for a live admin session (AA-3, AA-4) and 401
   otherwise. Relax the CSP for `/mlflow/*` only, to what the MLflow UI needs.
2. **Sim token:** `mlflow.{$DOMAIN}` keeps serving the sim server, but checks
   `Authorization: Bearer $MLFLOW_SIM_TOKEN` through the same endpoint instead of basic auth.
   Update `sim-run.ps1`, `compose.sim.yaml`, `env.server.example` and the LT02 tests.
3. **View audit (LT-29):** when the forwarded request reads traces (get trace, search traces),
   write `admin.trace_viewed` with the admin and the trace id or query.
4. **Controls switch (LT-19):** the admin Controls page gets "Pause production tracing", with a
   reason (AA-6), writing `llm_tracing_paused`.
5. **Docs:** `docs/hosting.md` "LLM tracing (MLflow)" updated for the admin path and the token.

## Tests

- LT-28: the auth endpoint answers 200 for an admin session, 401 without; a candidate session
  never passes; the Caddyfile routes `/mlflow/*` on the admin host through `forward_auth`; no
  site keeps basic auth.
- LT-29: a forwarded trace read writes `admin.trace_viewed`; other MLflow requests do not.
- LT-19: the switch writes the setting with a reason and an audit row.
