# LT02: MLflow locally and on the main server

Read `00-common.md` first.

- **Branch:** `feat/lt-02-infra`
- **Waits for:** LT00
- **Folders:** `infra/compose.yaml`, `infra/compose.server.yaml`, `infra/caddy/Caddyfile`,
  `infra/server/env.server.example`, `infra/sim/compose.sim.yaml`, `infra/sim/sim-run.ps1` (env
  only), `scripts/dev.ps1`, `docs/hosting.md`
- **Requirement IDs:** LT-11 (dev.ps1), LT-12, LT-13 (compose and env)

## Build

1. **Service (LT-12).** An `mlflow` service from the official MLflow image, pinned to the version
   LT01 picked (if LT01 has not merged yet, pick it and write it in both PRs). Backend store: a
   separate `mlflow` database in the existing Postgres (`postgresql://...` for the MLflow server
   itself). Artifacts: a named volume. A health check on `/health`.
2. **Local.** Add it to `infra/compose.yaml` in a new `obs` profile, on `localhost:5000`. In
   `scripts/dev.ps1`, add `obs` to the profile set: `up -Profile obs` starts it, creates the
   `mlflow` database if it is missing (idempotent), and then runs the dev prune from LT01 (skip
   with a note if LT01 is not on `main` yet). The local api, worker and voice get
   `MLFLOW_TRACKING_URI=http://mlflow:5000`, with `LLM_TRACING` and `LLM_TRACING_DEV` left off
   unless the developer sets them.
3. **Main server.** Add the service to `infra/compose.server.yaml` with `mem_limit: 1g`. Give
   api, worker, voice and sim `MLFLOW_TRACKING_URI=http://mlflow:5000` and
   `MLFLOW_EXPERIMENT=sim`. `LLM_TRACING` stays `off` in `env.server.example`, with a comment
   that turning it on traces sim sessions only.
4. **Caddy.** A new site `mlflow.{$DOMAIN}` with `basic_auth` (a hashed password from the server
   env) that proxies to `mlflow:5000`. Not on the app or admin hosts. Add the DNS step to
   `docs/hosting.md`.
5. **Sim server (LT-13).** `infra/sim/compose.sim.yaml` passes `MLFLOW_TRACKING_URI`,
   `MLFLOW_TRACKING_USERNAME` and `MLFLOW_TRACKING_PASSWORD`; `sim-run.ps1` writes them into
   `infra/sim/.env` from the local settings it already reads. Empty values mean the sim does not
   log to MLflow.
6. **Docs.** A "LLM tracing (MLflow)" section in `docs/hosting.md`: how to turn it on, how to open
   the UI, how to rotate the password, and the capacity check below.

## Capacity check

If you can reach the server, start a voice sim with tracing on and record MLflow's memory with
`docker stats`. Otherwise leave this for LT06 and say so in the PR.

## Tests

- A test (Python, like the existing infra tests if there are any, else in
  `packages/core/tests/`) that loads both compose files and checks: the `mlflow` service exists,
  is in the `obs` profile locally, has `mem_limit` on the server, and its image tag is an exact
  version.
- A test that the Caddyfile has an `mlflow.` site with `basic_auth`, and that no other site
  proxies to `mlflow`.

## Done when

- `docker compose -f infra/compose.yaml --profile obs config` is valid (run it if Docker is
  available; otherwise CI's compose check covers it).
- No secret is committed; the example env has placeholders only.
