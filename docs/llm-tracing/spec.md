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
It depends on `mlflow-skinny`, pinned to `3.17.2` (LT01), and so does the sim (LT05); the MLflow
server image (LT02) uses the same version. Not the lighter `mlflow-tracing`: it and
`mlflow-skinny` both install the `mlflow` package, so the two cannot share one environment, and
the sim needs skinny's run tracking.

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

## How to compare two prompt versions

1. Make sure tracing is on (`docs/hosting.md`, "LLM tracing (MLflow)") and
   `STRONGHIRE_MLFLOW_TOKEN` is set on your PC.
2. Run a suite on the current prompts: `./infra/sim/sim-run.ps1 -Suite text-smoke`.
3. Deploy the prompt change (a new `prompts/<role>/<name>.v<N+1>.txt`), then run the same suite
   again. Use the same suite and the same scenarios, so the runs differ only in the change.
4. Open `https://admin.getstronghire.com/mlflow/` (signed in to the admin app), experiment
   `sim`, tick both runs, and click **Compare**.
   - **Params** show what changed: `<role>.prompt_refs`, `<role>.alias`, `<role>.tier`,
     `model_profile`, `git_sha`.
   - **Metrics** show the effect:
     - `judge_<rule>_pass_rate`: quality, from the judge;
     - `turn_latency_p50_ms` and `turn_latency_p95_ms`, `<role>_ttft_p50_ms`: speed;
     - `server_cost_per_session_usd`: cost;
     - `structured_retries`, `validation_failures`, `gateway_errors`: failures.
5. To see why a number moved, open the **Traces** tab and filter by `tags.sim_run_id = '<run>'`
   or by `tags.scenario`. A session's turns and jobs group under its session id; the judge's
   reasons are the assessments on its `judge` trace.

A model comparison works the same way: change the role's alias in `config/models.<profile>.yaml`
instead of the prompt. Runs are small (a suite is a handful of sessions), so treat a single
difference as a lead, and run the suite twice before you act on it.

## Phase 2: production tracing (LT-16 to LT-31)

Phase 2 traces real users' sessions. It splits into two risk levels:

- **Metadata for every session** (when switched on): timings, tokens, cost, roles, aliases, tiers,
  prompt refs, retries and errors. No message text and no hashes.
- **Content only for users who opt in** with a new, separate consent, and then only the
  interview turns: what the interviewer said and what the candidate said, scrubbed.

The requirements are LT-16 to LT-31 in `docs/spec.md`. The build plan is
`docs/llm-tracing/phase2-plan.md`. The legal gates are `docs/llm-tracing/phase2-gates.md`.

### Phase 2 decisions

The owner agreed these on Nov 6, 2026. Do not reopen them in a task.

| ID | Decision |
| --- | --- |
| D-11 | **Scope.** Metadata for every real user's session; full content only with a new, separate, unticked consent (Law 25: consent specific to each purpose). `training_consent` is a different purpose and is not reused. |
| D-12 | **Consent.** An account toggle beside the training-data toggle (AC-2), off by default, for all future sessions. Turning it off stops content capture from the next turn and deletes the user's past content traces within 24 hours; their metadata traces stay. Every change is written to the audit log. |
| D-13 | **What content is.** The live interview turns only: the interviewer's reply and the candidate's answer (text, or the transcript of speech), scrubbed. Never the prompt messages (they carry the brief, which is built from the resume), and never the worker jobs (extraction, gap analysis, brief, scoring), which stay metadata-only even with consent. Scrubbing is `strong_core.ops.errors.scrub_text` (emails, phone numbers, URL queries) plus the user's own name and the companies in their resumes and job targets. |
| D-14 | **Retention.** Production content traces 30 days, production metadata traces 90 days, deleted by a daily job. MLflow's database follows the 30-day backup rotation. |
| D-15 | **Access.** People reach MLflow only through the admin app: at `admin.{$DOMAIN}/mlflow/`, where Caddy's `forward_auth` asks the API to check the admin session (AA-3, AA-4). Each read of a production trace is written to the audit log (AA-6). Production traces live in their own `prod` experiment. |
| D-16 | **Volume.** Every session is traced, with a per-session sample rate (`LLM_TRACING_SAMPLE`, default 1.0; a session is traced whole or not at all) and an off switch on the admin Controls page (a runtime setting, no deploy). |
| D-17 | **Gates.** Two flags, both off by default. `LLM_TRACING_PROD` (metadata) goes on once the privacy policy and the retention schedule describe it. `LLM_TRACING_PROD_CONTENT` (the consent toggle and content capture) goes on only after the privacy lawyer approves the consent wording and the PIA update. The toggle is not shown while that flag is off. |
| D-18 | **Deletion.** Account deletion and consent withdrawal queue a `delete_traces` worker job. Arq retries it; if it has not succeeded 12 hours after it was asked for, an alert goes to `ALERT_EMAIL`. Its completion is written to the audit log. Every production trace carries `org_id` so one query finds a user's traces even after their rows are gone. |

### Phase 2 design

**Content in its own trace (LT-23).** MLflow cannot strip the text from a stored trace, but
withdrawal (D-12) and retention (D-14) must remove content and keep metadata. So a consenting
user's turn writes two traces:

- the metadata `turn` trace, as for everyone;
- a `turn.content` trace with the same tags plus `content=turns`, holding the interviewer's reply
  and the candidate's answer for that turn, scrubbed.

Withdrawal and the 30-day retention delete only `turn.content` traces; the metadata stays.

**Content modes.** Phase 1 has `full` and `redacted` (a SHA-256 and a length). Phase 2 adds
`metadata`: message counts and lengths only, no hash, no error message. Every real user's span is
`metadata`, consent or not; content goes only into `turn.content` (D-13).

**Who is traced (LT-16, LT-19).** `strong_core.tracing.sessions.trace_tags_for()` gains a
production branch for a real user's session, in this order:

1. phase 1 rules first: a sim session is traced as before;
2. `LLM_TRACING_PROD` off, or the runtime setting `llm_tracing_paused` on: not traced;
3. the session falls outside `LLM_TRACING_SAMPLE` (a stable hash of the session id): not traced;
4. otherwise metadata tags: experiment `prod`, `org_id`, `session_id`, service, release,
   model profile, content `metadata`, and `turn_content=on` when `LLM_TRACING_PROD_CONTENT` is on
   and the user's `tracing_consent` is on at the start of the turn.

Any lookup failure means not traced (fail closed).

**Where the turn text comes from.** The API's text turns and the voice agent already hold the
candidate's answer and the interviewer's reply as `Turn` rows. The content trace is written from
those, after scrubbing, not from the gateway's prompt messages.

**Scrubbing (LT-22).** `strong_core.tracing.scrub` builds a scrubber per session from the user's
profile name and the company names in their resumes and job targets, and applies it after
`scrub_text`. Names become `[name]`, companies `[company]`. Matching is case-insensitive on word
boundaries. It is best effort: a nickname or a colleague's name can survive, which the consent
wording says plainly.

**Access path (LT-28, LT-29).**

- The admin cookie `sh_admin` is host-only on `admin.` and `SameSite=Strict` (AA-3), so the
  browser never sends it to `mlflow.{$DOMAIN}`. The MLflow UI therefore moves under the admin
  host: `admin.{$DOMAIN}/mlflow/*`, with the server's `--static-prefix /mlflow`.
- Caddy calls `GET /api/admin/mlflow-auth` with `forward_auth` for every `/mlflow/*` request. The
  API answers 200 for a live admin session, else 401.
- The MLflow UI needs inline scripts, so the strict admin CSP (AA-9) is relaxed for `/mlflow/*`
  only, to what the UI needs and no more.
- When the forwarded request reads a trace (the trace-get and search endpoints), the API writes
  `admin.trace_viewed` to the audit log with the admin and the trace or search, as AA-6 does for
  the existing trace views.
- `mlflow.{$DOMAIN}` stays for the sim server only, and its basic auth is replaced by a machine
  token (`MLFLOW_SIM_TOKEN`) checked by the same `forward_auth` endpoint.

**Deletion (LT-24 to LT-26).** `delete_traces(org_id, scope)` searches the `prod` experiment by
`tags.org_id` (and `content=turns` for a withdrawal) and deletes the trace ids in batches. Account
deletion asks for scope `all`; withdrawal asks for scope `content`. The job records
`tracing.traces_deleted` with the count when it succeeds. A check in the existing alert engine
fires when a request is older than 12 hours and still not done.

**Retention (LT-27).** The existing daily retention job (`strong_worker.retention`) gains a step:
delete `prod` traces with `content=turns` older than 30 days, and all other `prod` traces older
than 90 days.

### Phase 2 open items

- The consent wording, approved by the privacy lawyer (gate 2).
- The privacy policy and retention schedule text (gate 1), and the PIA update (gate 2).
- Measured MLflow memory use under production volume.
