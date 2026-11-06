# LT03: Sim-only trace context in the API and worker

Read `00-common.md` first.

- **Branch:** `feat/lt-03-api-worker`
- **Waits for:** LT01
- **Folders:** `apps/api/src/strong_api/sessions/`, `apps/api/src/strong_api/auth/sim.py`,
  `apps/worker/src/strong_worker/ops/context.py`, their tests
- **Requirement IDs:** LT-3, LT-6 (text), LT-7, LT-14 (headers)

## Build

1. **Headers (LT-14).** On the routes that create an interview session, read `X-Sim-Run` and
   `X-Sim-Trace-Content`. Only when the user is a sim user (`is_sim_user`), validate them into
   `SessionTraceSettings` and store them in `interview_sessions.trace_json`. For any other user,
   ignore them. An invalid value stores `content="redacted"`.
2. **One helper** in the API that returns the trace context for a session: `None` unless the
   session's user is a sim user; else `TraceTags` from `trace_json` (redacted when absent), with
   `service="api"`, `release`, `model_profile` and `session_id` (LT-7). Cache the sim-user check
   for the length of the request.
3. **API.** Wherever the sessions code sets `usage_context(session.org_id, session.id)`, also
   enter the trace context from the helper. Wrap each text interview turn in `turn_span("text",
   n)` (LT-6).
4. **Worker.** In `job_context` (`strong_worker/ops/context.py`), when the job has a session, load
   the same settings and open one trace per job, named after the job function (LT-7).
5. **Local dev.** With `LLM_TRACING_DEV=on`, a local (non-server) process sets a redacted trace
   context for every session, in the `dev` experiment. Never on the server: the server env does
   not set it, and the helper refuses when `MODEL_PROFILE` is a production profile.

## Tests

- LT-3: a session of a normal user makes no span, even with the sim headers sent; a sim user's
  session does.
- LT-14: headers from a non-sim user are not stored; a sim user's are; a bad value becomes
  `redacted`.
- LT-6: a sim text turn makes one `turn` span whose children are the turn's gateway spans.
- LT-7: span tags include `session_id`, `sim_run_id` and `scenario`; a scoring job is one trace
  named after the job.

## Done when

- All existing session and worker tests pass unchanged.
