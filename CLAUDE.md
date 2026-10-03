# Strong Hire: instructions for Claude Code

Strong Hire is a voice interview simulator for tech candidates. The full product and technical
spec is `docs/spec.md`. Read the sections that touch your task before you change code.

## Layout and folder ownership

| Folder | Contents | Owner |
| --- | --- | --- |
| `packages/core` | Python package `strong_core`: config, Pydantic contracts, SQLAlchemy models, Alembic migrations, model gateway, prompt loader | Shared. Change only through a small, separate PR that merges first. |
| `apps/api` | FastAPI service (`strong_api`) | API workstreams |
| `apps/worker` | Arq background jobs (`strong_worker`) | Worker workstreams |
| `apps/voice` | LiveKit Agents voice agent (`strong_voice`), stub until P1 | P1, P7 |
| `apps/web` | React + Vite + TypeScript front end | P3 and UI workstreams |
| `prompts/<role>/` | LLM prompt templates, `<name>.v<N>.txt` | The workstream that owns the role |
| `config/` | `models.<profile>.yaml` (role to model alias, capabilities), `litellm.<profile>.yaml` (real model ids) | P1 |
| `schemas/` | JSON Schemas generated from `strong_core.schemas`. Never edit by hand. | Generated |
| `profiles/` | Company profile JSON files | R1 research, P4 import |
| `evals/` | Eval harness and fixtures | P5, P11 |
| `infra/` | `compose.yaml`, Dockerfiles, Caddy config | P0, P12 |
| `scripts/` | PowerShell helpers (`dev.ps1`) | P0 |

Each prompt file in the execution plan lists the folders it owns. A session may read anything.
It edits only its own folders and its own tests.

## Commands

The developer machine is Windows with PowerShell. Do not add bash-only scripts.

```powershell
./scripts/dev.ps1 up [-Profile core|models|voice|all]   # start the Docker stack, then migrate
./scripts/dev.ps1 down [-Volumes]
./scripts/dev.ps1 logs [-Service api]
./scripts/dev.ps1 test      # pytest with MODEL_PROFILE=fake, then Vitest
./scripts/dev.ps1 lint      # ruff, mypy, schema freshness, ESLint, tsc
./scripts/dev.ps1 migrate   # alembic upgrade head inside the api container
./scripts/dev.ps1 seed      # the 20 launch companies
./scripts/dev.ps1 schemas   # regenerate schemas/ after changing a contract
```

Without Docker: `uv sync --all-packages`, then `uv run pytest`, `uv run ruff check .`,
`uv run mypy`. For the web app: `pnpm --dir apps/web install`, then `test`, `lint`, `dev`.

Note: on networks with TLS inspection, `uv` can fail to load the CA file in `SSL_CERT_FILE`.
`dev.ps1` removes that variable for `uv` calls and sets `UV_NATIVE_TLS=1`.

## The gateway rule

- All model calls go through `strong_core.gateway` (`get_gateway()`). No other module may import
  `pydantic_ai`, `openai`, `litellm` or another model SDK. A test enforces this.
- Code asks for a role: `extractor`, `planner`, `interviewer`, `scorer`, `stt`, `tts`.
  `config/models.<MODEL_PROFILE>.yaml` maps each role to a LiteLLM alias.
- Never write a model name or provider in code. Real model ids appear only in
  `config/litellm.*.yaml`. A test scans the code for model names.
- To change behavior by model, check `gateway.capabilities(role)` (`supports_tools`,
  `json_mode`, `context_window`). Never check a model name.
- Structured output: `await gateway.complete(role, messages, output_type=SomeContract)`.
  Pydantic AI validates it and retries once.
- Prompts come from `strong_core.prompts.load_prompt(role, name)`, never inline strings.
  `PromptTemplate.message(...)` sets `prompt_ref`, and `Completion.prompt_refs` reports it.
  Store the prompt ref with the output, for example `Scorecard.rubric_version`.

## The fake-model rule for tests

- Tests and CI run with `MODEL_PROFILE=fake`. No test may call a real model or the network.
- The fake model returns fixtures from `packages/core/src/strong_core/gateway/fixtures/<role>/`:
  an exact recording `<messages-hash>.json|.txt`, else `<OutputType>.json`, else `text.txt`.
- When a test needs a new reply, add a fixture file. The `FakeFixtureMissingError` message gives
  the file name and the hash.
- A test checks that every `<OutputType>.json` fixture validates against its contract.

## Contracts and schemas

- Contracts live in `strong_core.schemas`. They reject unknown fields.
- After any contract change, run `./scripts/dev.ps1 schemas` and commit `schemas/`.
  CI fails when `schemas/` does not match the models.

## Migration rules

- Every schema change is a new Alembic migration in `packages/core/migrations/versions/`.
  Never edit a migration that is on `main`.
- Generate with
  `uv run alembic -c packages/core/alembic.ini revision --autogenerate -m "<what>"`,
  then read and fix the file. Autogenerate writes each enum CHECK constraint twice; delete the
  `sa.CheckConstraint(...)` lines, because `sa.Enum(create_constraint=True)` already creates them.
- Every migration must have a working `downgrade()`. CI runs upgrade, `alembic check`,
  downgrade to base, and upgrade again on a fresh Postgres 16.
- Every user-owned table has a non-null `org_id` foreign key to `orgs`. Add new user-owned
  tables to `USER_OWNED_TABLES` in `strong_core/db/models.py`; a test checks the column.
- If two open PRs both add a migration, the second to merge rebases and fixes `down_revision`.
- Async code uses asyncpg (`strong_core.db.get_engine()`). Alembic and scripts use psycopg.
  `DATABASE_URL` is always written with `postgresql+psycopg://`.

## Branches, PRs and requirement IDs

- Branch names: `feat/pN-short-name`, for example `feat/p2-inputs`.
- All work merges into `main` through a pull request with green CI.
- Requirement IDs from `docs/spec.md` (IN-1, GA-2, IV-3, FB-1, PL-1, ...) are the acceptance
  tests. Put the ID in the test docstring or name, and list the IDs in the PR description.
  An ID counts as done only when at least one test covers it.
- Keep tests green on every commit.
