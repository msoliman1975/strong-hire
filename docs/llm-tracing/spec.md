# LLM tracing with MLflow (LT)

Strong Hire records every model call as an MLflow trace, so the team can compare prompt and model
versions on the same sim scenarios and see where latency and failures come from. Phase 1 traces
sim and dev traffic only. Real users' traffic is phase 2, behind a flag, after its consent,
redaction, retention and deletion rules are designed (D-1).

The requirements are LT-1 to LT-16 in `docs/spec.md`. The build plan is
`docs/llm-tracing/execution-plan.md`.

## Why, and what it adds

Some of this already exists:

| Need | Already there | What MLflow adds |
| --- | --- | --- |
| Cost per call and session | `usage_events` (OB-2), admin cost pages (AD-2, AI-2) | Cost on each span, next to its prompt ref and latency |
| Voice latency | `voice_turn_timings` (OB-3), `strong_voice.latency` | One trace per turn: STT, LLM and TTS as child spans |
| Quality | `strong_sim.judge`, `evals/` | Judge verdicts beside cost and latency in one run comparison |
| Prompt versions | `Completion.prompt_refs` | Runs compared side by side by prompt ref and model alias |
| Debugging | `RecordingGateway`, error events (OB-4) | The full prompt and reply of a failed or slow call (fixture personas only) |

MLflow does not replace any of these. `usage_events` stays the source of truth for cost, and the
admin pages keep reading it. Spans copy the same numbers.

## Decisions

The owner agreed these on Nov 5, 2026. Do not reopen them in a task.

| ID | Decision |
| --- | --- |
| D-1 | **Scope.** Phase 1 traces sim runs (suites from `sim-run.ps1` and single admin sims, SM) and local dev runs. Real users' traffic is never traced in phase 1. Phase 2 adds production behind a flag, after its own design for consent (`training_consent` or a new flag), redaction, retention and account deletion (Quebec Law 25, CCPA). |
| D-2 | **Goal.** Compare prompt and model versions (main goal), with latency and failures alongside. Quality comes from the existing judge only (D-7). |
| D-3 | **Where MLflow runs.** One long-lived MLflow server on the main server (`stronghire-test`, cx43, 16 GB), plus a local instance for dev in the `obs` compose profile. The sim server is deleted after each run, so it never hosts MLflow; it sends its data to the main server's MLflow. `MLFLOW_TRACKING_URI` chooses the target. |
| D-4 | **Who traces.** The interviewer and scorer of a sim session run on the main server (api, worker, voice), not on the sim server. So those services trace, but only calls inside a sim user's session (`is_sim_user`). The sim process traces its own candidate and judge calls. |
| D-5 | **One MLflow run per sim suite run.** A single admin sim is a run with one scenario. Params say what made the run different; metrics are the suite's totals. Each session's traces are tagged with the run and the scenario. Local dev traffic goes to a `dev` experiment with no run. |
| D-6 | **Content.** Full message content only for sim sessions on a fixture persona. A scenario with a pasted resume or job (SM-17, SM-18), and all dev traffic, store a SHA-256 hash and a length instead of each message body. Timings, tokens, cost, roles, aliases and prompt refs are always kept. When the content mode is unknown, redact. Dev traces are deleted after 30 days. |
| D-7 | **Quality signal.** The existing judge (`strong_sim.judge`, 8 rules) goes into MLflow as assessments, with each rule's pass rate as a run metric. No new LLM scorer, no new model cost. |
| D-8 | **Span depth.** Gateway spans, plus a `turn` parent span for each voice or text interview turn. No API, DB or worker auto-instrumentation: that is Sentry's and Prometheus's job. |
| D-9 | **Manual spans, not autolog.** The gateway opens spans itself with the MLflow tracing API. Pydantic AI autolog would trace every call, with no way to gate by sim user (D-4) or redact (D-6). |
| D-10 | **Never slow or break a call.** Export is asynchronous and batched. An unreachable or failing tracking server costs no latency on the call path and never raises; failures are logged at most once a minute. |

## Technical design

### Core: `strong_core.tracing`

A new module in `packages/core`, the only place outside `strong_sim` that imports MLflow (LT-15).
It depends on the `mlflow-tracing` package (the light tracing SDK), pinned to `3.17.2` (LT01).
The MLflow server image (LT02) and `mlflow-skinny` in the sim (LT05) use the same version.

Spans are recorded as plain Python records while the code runs, so the call path does no MLflow
work. When a trace's root span ends, the finished tree goes on a bounded queue; one background
thread replays it into MLflow with `mlflow.start_span_no_context`, using the recorded start and
end times.

- **Settings.** `LLM_TRACING` (`off` by default, or `on`), `MLFLOW_TRACKING_URI`,
  `MLFLOW_EXPERIMENT` (default `dev`), and the tracking credentials for the Caddy route (LT-13).
  Tracing is active only when `LLM_TRACING=on`, a URI is set, and `MODEL_PROFILE` is not `fake`.
  Otherwise every function in the module does nothing and imports nothing heavy (LT-1).
- **Trace context.** A context variable like `usage_context`:

  ```python
  with trace_context(TraceTags(session_id=..., sim_run_id=..., scenario=..., content="full")):
      ...  # gateway calls in here are traced
  ```

  Gateway calls with no trace context are not traced (LT-3). The services set the context only
  for sim users' sessions. Local dev processes set it with `content="redacted"` around their own
  calls, through a dev setting (`LLM_TRACING_DEV=on`), so a developer sees their local traffic.
- **Gateway spans (LT-2).** `ModelGateway.complete`, `stream`, `transcribe`, `synthesize` and
  `synthesize_stream` open one span each, at the same point where usage is reported today, so no
  caller can skip it. Attributes:
  - `role`, the LiteLLM `alias` and the `tier` (from `gateway.capabilities`). Never a model name
    in code: the alias comes from config.
  - `prompt_refs`, the output type name, and whether structured output validated on the first try
    or needed the retry.
  - input and output tokens, `cost_usd` and `cost_known`, the same numbers written to
    `usage_events`.
  - `duration_ms`; for `stream`, also `ttft_ms` (first text delta).
  - on failure: the exception type and a scrubbed message, with span status `ERROR`.
  - inputs and outputs: the messages and reply when `content="full"`, else a hash and a length
    for each (LT-4).
- **Turn spans (LT-6).** `turn_span(kind="voice"|"text", index=n)` opens a parent span. Gateway
  calls inside it become its children. The caller sets timing attributes when the turn ends.
- **Prune (LT-11).** `python -m strong_core.tracing prune --experiment dev --days 30` deletes older
  traces through the MLflow client.

### Session trace settings (LT-14)

Only the sim knows whether a scenario uses a fixture persona and which suite run a session belongs
to. It tells the server when it creates the session:

- headers `X-Sim-Run: <run id>`, `X-Sim-Scenario: <scenario id>` and
  `X-Sim-Trace-Content: full|redacted` on `POST /sessions`, the one route that creates a session;
- the API honours them only for a sim user, and stores them on the session in a new nullable
  `interview_sessions.trace_json` column (contract `SessionTraceSettings`: `sim_run_id`,
  `scenario`, `content`). A missing or invalid value means `content="redacted"`;
- the api, the worker and the voice agent read `trace_json` where they already set
  `usage_context`, and set `trace_context` from it when the session's user is a sim user.

### Services

| Service | Where | What it traces |
| --- | --- | --- |
| api | `sessions/router.py` text turns, and every `usage_context` site for a sim session | a `turn` span for each text turn; gateway spans |
| worker | `strong_worker/ops/context.py` (the job wrapper that sets `usage_context`) | one trace for each job (scoring, debrief, brief), named after the job |
| voice | `strong_voice/agent.py` and the interview agent | a `turn` span for each interviewer turn, with `e2e_ms`, `turn_detection_ms`, `stt_ms`, `llm_ttft_ms`, `tts_ttfb_ms`, `other_ms` from the same metrics `latency.py` reads (OB-3) |
| sim | `strong_sim.runner` and `serve` | the MLflow run; its own candidate and judge calls; judge assessments |

All traces carry the tags `service`, `release` (git SHA), `model_profile`, `session_id`, and for
sim sessions `sim_run_id` and `scenario` (LT-7). MLflow's session metadata is set to `session_id`,
so the UI groups a session's turns and jobs together.

### Sim runs (LT-8 to LT-10)

`strong_sim` depends on `mlflow-skinny` (the tracking client), pinned.

- At the start of a suite run, the runner starts an MLflow run in the `sim` experiment. Params:
  suite name, source (`suite` or `admin`), model profile, the alias and tier of each role, git
  SHA, and scenario count.
- Each session is created with `X-Sim-Run` and `X-Sim-Trace-Content`. `full` only when the
  scenario has no `cv_text` and no `job_text`.
- The judge call for each session runs inside a sim-side trace tagged with the session. The
  verdict is attached to that trace as one MLflow assessment per rule: name, pass, fail or
  not_applicable, rationale, and the rubric prompt ref (LT-9).
- At the end, the runner logs metrics. Some come from the run's existing report (`report.py`):
  sessions done and failed, cost per session, p50 and p95 turn latency. Others come from the
  run's traces (search by `sim_run_id`): p50 and p95 `llm_ttft_ms` for each role, retry count,
  validation failures, gateway errors. Each judge rule's pass rate is a metric too. The HTML
  report and a per-session table (`log_table`) are attached as artifacts.
- The prompt refs seen in the traces, for each role, are logged as params, so two runs with
  different prompt versions show the difference in the compare view.
- A failing MLflow server never fails a sim run (D-10). The run's files on disk stay the full
  record.

### Infrastructure (LT-12, LT-13)

- **Image.** One `mlflow` service from the official MLflow image, pinned to an exact version
  matching the clients.
- **Local.** `infra/compose.yaml` gets the `mlflow` service in a new `obs` profile, on
  `localhost:5000`. Its backend store is a separate `mlflow` database in the existing Postgres; a
  named volume holds artifacts. `./scripts/dev.ps1 up -Profile obs` starts it, creates the
  database if needed, and runs the dev prune (LT-11).
- **Main server.** `infra/compose.server.yaml` gets the same service with `mem_limit: 1g`,
  reached only through Caddy at `mlflow.{$DOMAIN}` with `basic_auth` (credentials from the
  server's env). The api, worker and voice reach it on the internal network at
  `http://mlflow:5000`. The admin app does not link to it in phase 1. DNS needs an
  `mlflow.` record.
- **Sim server.** `infra/sim/compose.sim.yaml` passes `MLFLOW_TRACKING_URI`
  (`https://mlflow.<domain>`) and the basic-auth credentials from `infra/sim/.env`, which
  `sim-run.ps1` writes.
- **Capacity.** The cx43 has 16 GB. MLflow with a few workers needs about 300 to 600 MB. The
  infra task checks free memory under a voice sim and writes the result in `docs/hosting.md`.

### Testing

- All tests run with `MODEL_PROFILE=fake`, where tracing is a no-op. Tests that check spans
  replace the exporter with an in-memory one (a fixture in `strong_core.tracing.testing`) and
  never reach a network.
- A test proves that a call outside a trace context, and a call for a non-sim user, make no span
  (LT-3).
- A test proves that an unreachable tracking URI adds no exception, and that span bookkeeping
  stays under 2 ms p95 per call (LT-5).
- A test proves that a redacted span holds no message text (LT-4).

## Phase 2: production (not built now)

Before any real user's call is traced, a separate design must decide:

- the consent basis and the setting that controls it;
- the redaction rules (resumes, transcripts, names, emails);
- a retention period (90 days like `voice_turn_timings` is the starting point);
- deletion of a user's traces when the account is deleted (AC rules, Law 25);
- whether MLflow stays on the main server or moves.

LT-16 records this as an open item.
