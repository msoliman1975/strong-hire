# LLM tracing: rules for every task

Read this file, then your task's prompt file. The task prompt names its branch, dependencies,
folders and requirement IDs.

## Sources and precedence

1. `docs/llm-tracing/spec.md`: decisions D-1 to D-10 and the technical design. The owner agreed
   every decision there; do not reopen them.
2. The LT table in `docs/spec.md`: the acceptance tests.
3. `docs/spec.md`, `docs/admin-spec.md` (OB, SM), `docs/sim-candidate.md` and `CLAUDE.md` cover
   everything else, including:
   - the gateway rule and the fake-model rule;
   - contracts and schemas, and migrations;
   - folder ownership.

When a question is still open, choose what is closest to the spec's decisions. Write the choice
under "Decisions" in your PR and carry on.

## Rules that apply everywhere

- **No real user is traced (D-1, LT-3).** Every place that sets a trace context checks
  `is_sim_user` first, or is the local dev setting. When in doubt, do not trace.
- **Redact by default (D-6, LT-4).** Content is stored only with `content="full"`. Any missing,
  unknown or invalid value means redacted.
- **Tracing never breaks or slows a call (D-10, LT-5).** No tracing error may reach a caller. Do
  not await the network on the call path.
- **MLflow imports only in `strong_core.tracing` and `strong_sim` (LT-15).** Every other module
  uses the `strong_core.tracing` API.
- **No model names in code.** Spans carry the role, the alias and the tier from config.
- **`usage_events` stays the source of truth for cost.** Spans copy the same numbers; nothing
  reads cost back from MLflow except the sim's run metrics.
- **No real model, MLflow server or network in any test.** Tests use `MODEL_PROFILE=fake` and the
  in-memory exporter fixture from LT01 (`strong_core.tracing.testing`).
- **Pin versions.** `mlflow-skinny` (core and sim) and the MLflow server image use one exact,
  matching version.

## Checks before every push

```bash
uv run ruff check .
```

```bash
uv run ruff format --check .
```

```bash
uv run mypy
```

```bash
MODEL_PROFILE=fake uv run pytest -q
```

After any contract change, regenerate `schemas/` the way `scripts/dev.ps1 schemas` does (read
that script for the underlying `uv run` command) and commit the result. If the OpenAPI schema
changed, regenerate the web and admin API types too.

If Postgres 16 is available in the container, run the migration round trip: upgrade, `alembic
check`, downgrade to base, upgrade. Otherwise CI runs it.

Do not add bash-only scripts to the repo; the developer machine is Windows.

## Tests and requirement IDs

Every requirement ID your task lists gets at least one test with the ID in its name or docstring.

## PR template

Title: `LLM tracing LT<NN>: <task title> (<IDs>)`

```markdown
## What
One paragraph.

## Requirement IDs
- LT-x: test name
- …

## Decisions
- …

## Checklist
- [ ] Done-when items from the task prompt
- [ ] ruff, mypy, pytest
- [ ] Schemas regenerated (if contracts changed)
- [ ] No real user's call can be traced (LT-3)
```

End the PR description with the attribution lines from your system prompt.

## Commits

Small, green commits with clear messages, each ending with the attribution lines from your system
prompt. Never commit secrets, `.env` files or MLflow data.
