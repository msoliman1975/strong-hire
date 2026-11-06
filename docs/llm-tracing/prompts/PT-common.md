# LLM tracing phase 2: extra rules for every PT task

Read `00-common.md` first; it still applies. These rules come on top, because phase 2 touches real
users' data.

- **Decisions D-11 to D-18** in `docs/llm-tracing/spec.md` are agreed. Do not reopen them.
- **Fail closed (LT-31).** Any doubt, error or missing value means the session or turn is not
  traced. Never fall back to tracing.
- **Never text in a production span (LT-17).** A real user's gateway spans are `metadata` mode.
  The only place text may go is a `turn.content` trace, and only when the turn's tags say
  `turn_content=on`.
- **Content is the turns, scrubbed (LT-21, LT-22).** Build it from the interviewer's reply and the
  candidate's answer, never from prompt messages, and always through the PT01 scrubber.
- **Admins never see resume content (AA-11).** No task adds a route or trace that exposes resume
  text, gap findings, scores or the brief.
- **Both flags stay off by default** (`LLM_TRACING_PROD`, `LLM_TRACING_PROD_CONTENT`) in code,
  compose files and example env files.
- **Every test that checks privacy names the leak it rules out**, for example: "a real user's
  answer never appears in a metadata span".
