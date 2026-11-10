# PT01: Core for production tracing

Read `00-common.md` and `PT-common.md` first.

- **Branch:** `feat/pt-01-core`
- **Waits for:** PT00
- **Folders:** `packages/core` (src, tests, migrations), `schemas/`, `.env.example`
- **Requirement IDs:** LT-16, LT-17, LT-18, LT-19 (the rule), LT-20 (model), LT-22, LT-23, LT-31

## Build

1. **Settings:** `LLM_TRACING_PROD` (off), `LLM_TRACING_PROD_CONTENT` (off), `LLM_TRACING_SAMPLE`
   (1.0, 0 to 1), `MLFLOW_PROD_EXPERIMENT` (`prod`). Document them, off, in `.env.example`.
2. **Runtime setting** `llm_tracing_paused` (bool, default false) in `strong_core.runtime_settings`.
3. **Column:** `users.tracing_consent` (bool, default false, server default false) and
   `users.tracing_consent_at` (nullable timestamp). Migration with a working downgrade.
4. **Content mode `metadata`** in `strong_core.tracing`: messages become
   `{"role", "prompt_ref"?, "len"}`, outputs `{"len"}`, no hash, no error message (LT-17).
5. **`TraceTags`** gains `org_id` and `turn_content` (bool); `as_tags()` includes `org_id` (LT-18).
6. **Production rule** in `trace_tags_for()` (spec "Who is traced"): sim first; then
   `LLM_TRACING_PROD`, `llm_tracing_paused`, the sample, then metadata tags in the `prod`
   experiment with `turn_content` from `LLM_TRACING_PROD_CONTENT` and the user's consent. The
   pause and consent reads take the caller's DB session. Any error: `None` (LT-31). The sample is
   a stable hash of the session id (`sha256`, first 8 bytes, divided by 2^64) below the rate.
7. **Scrubber** `strong_core.tracing.scrub`: `Scrubber.for_org(db, org_id)` loads the profile name
   and the company names from the org's resumes and job targets; `scrub(text)` applies
   `scrub_text`, then `[name]` and `[company]`, case-insensitive on word boundaries, longest name
   first (LT-22). Skip names shorter than 2 characters.
8. **Content trace** `record_turn_content(tags, index, kind, interviewer, candidate, scrubber)`:
   emits a `turn.content` trace (tags plus `content=turns`) only when `tags.turn_content` is true;
   never raises (LT-23).
9. **Deletion helpers** (MLflow side, in `strong_core.tracing.prod`): `delete_org_traces(org_id,
   scope)` with scope `all` or `content`, and `prune_prod(content_days, metadata_days)`, both
   searching the `prod` experiment by tag and deleting in batches, returning counts. They use the
   MLflow client and may raise; the worker (PT03) retries.

## Tests

- LT-16: with both flags off, a real user's session gets no tags; with `LLM_TRACING_PROD` on it
  gets `prod` metadata tags; sim sessions are unchanged.
- LT-17: a real user's spans hold none of the session's text, no `sha256`, no `error.message`.
- LT-18: production tags include `org_id` and `session_id`.
- LT-19: the sample keeps a session whole (same answer for every call); `llm_tracing_paused`
  stops tracing; sim tracing is not paused.
- LT-20 (model): consent defaults off; migration round trip.
- LT-22: the scrubber removes the profile name, companies, emails and phones; leaves other words.
- LT-23: `record_turn_content` writes a `turn.content` trace only with `turn_content`; content is
  scrubbed; the metadata trace is separate.
- LT-31: a failing consent or settings read means no tags, and nothing raises.
- Deletion helpers: with a fake MLflow client, the right filters and batch deletes.
