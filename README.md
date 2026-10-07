# Strong Hire

A voice interview simulator for tech candidates. The product and technical spec is
[docs/spec.md](docs/spec.md). Instructions for Claude Code are in [CLAUDE.md](CLAUDE.md).

## Setup on Windows

1. Install Docker Desktop with the WSL2 backend, Git, and the GitHub CLI (`gh`).
2. Install Node.js 20 or later, then pnpm: `npm install -g pnpm`.
3. Install Python 3.12 and `uv` (<https://docs.astral.sh/uv/>).
4. Clone the repo: `gh repo clone msoliman1975/strong-hire`, then `cd strong-hire`.
5. Start Docker Desktop and wait until it says that the engine is running.
6. Start the core stack: `./scripts/dev.ps1 up`. The first run builds the images and takes a few minutes.
   It also creates `.env` from `.env.example` and applies the database migrations.
7. Open <http://localhost:5180>. The page shows "API status: OK".
8. Load the 20 launch companies: `./scripts/dev.ps1 seed`.
9. Install the local Python tools: `uv sync --all-packages`.
10. Install the web tools: `pnpm --dir apps/web install`.
11. Run the tests: `./scripts/dev.ps1 test`. Run the linters: `./scripts/dev.ps1 lint`.
12. Optional, local models and voice: `./scripts/models.ps1 pull` (pulls the models named in
    `config/`), then `./scripts/models.ps1 smoke` and see [apps/voice/README.md](apps/voice/README.md).
13. Stop everything: `./scripts/dev.ps1 down`. Add `-Volumes` to delete the database too.

Note: if your network inspects TLS traffic, `up` copies the CA file named in `SSL_CERT_FILE`
into `infra/certs/` so the Docker builds trust it. See [infra/certs/README.md](infra/certs/README.md).

## Docker profiles and host ports

All ports are set in `.env` (see `.env.example`).

| Profile | Service | Host port | Notes |
| --- | --- | --- | --- |
| core | web (Vite dev server) | 5180 | Calls the API through `/api` |
| core | api (FastAPI) | 8700 | `GET /health` checks Postgres and Redis |
| core | worker (Arq) | none | Health check: `arq --check` |
| core | postgres 16 | 55432 | User, password and database: `strong` |
| core | redis 7 | 56379 | |
| models | ollama (CPU) | 11435 | Not 11434, so it does not clash with Ollama on the host |
| models | litellm proxy | 4000 | Loads `config/litellm.<LITELLM_PROFILE>.yaml` |
| voice | livekit-server (dev mode) | 7880, 7881, 7882/udp | Keys: `devkey` / `secret` |
| voice | voice agent | 8081 | `/health`; dev test page at <http://localhost:8081> |
| voice | stt (faster-whisper, CPU, int8) | 8010 | OpenAI-compatible `/v1/audio/transcriptions` |
| voice | tts (Kokoro, CPU) | 8880 | OpenAI-compatible `/v1/audio/speech`, streaming PCM |

The `all-in-one` profile starts every service above, for the `tiny` model profile.

## Text interview (dev only)

Dev builds also have a page that runs the interview as text, at
<http://localhost:5180/dev/interview> ("Text interview (dev)" in the top bar). You pick a job and the
interview settings, type your answers, and see the real debrief at the end. It uses the text channel of
the sessions API with the active model profile, for example `claude`.

## Run the CI checks locally

When GitHub Actions cannot run (for example, no Actions minutes left), run the same checks here and
paste the summary into the pull request:

```powershell
./scripts/check.ps1 -Report var/check.md   # python, migrations, web (with Playwright e2e)
./scripts/check.ps1 -SkipE2E               # without the Playwright browser tests
./scripts/check.ps1 -Docker                # also the Docker stack check
```

The tests do not read your `.env`, as in CI. Migrations run on a new Postgres 16 container that is
removed afterwards. The local-models and voice jobs are not included. About 6 minutes on a laptop.

## Model profiles

`MODEL_PROFILE` picks how the model gateway works:

- `fake`: recorded fixtures, no model. The default, and the only profile tests use.
- `tiny`: `config/models.tiny.yaml`. One small model (Qwen 2.5 3B) serves all four text roles, on CPU.
  For the smallest machine: set `MODEL_PROFILE=tiny` and `LITELLM_PROFILE=tiny` in `.env`, run
  `./scripts/models.ps1 pull -Profile tiny`, then start the `all-in-one` Docker profile.
  Results are development data (PL-6), and interviewing is weak.
- `local`: `config/models.local.yaml`, through LiteLLM to Ollama in Docker.
- `hosted`: `config/models.hosted.yaml`, through LiteLLM to hosted APIs. Needs `HOSTED_API_KEY` in `.env`.
- `claude`: `config/models.claude.yaml`. Claude Haiku 4.5 (extractor, interviewer) and Claude Sonnet 5.5
  (planner, scorer); speech-to-text and text-to-speech stay local. Needs `ANTHROPIC_API_KEY` as an
  environment variable (a Windows user variable is fine); it is never written to a file.

### Switch profiles

```powershell
./scripts/profile.ps1 status     # current profile; for claude, spend today against the budget
./scripts/profile.ps1 claude     # or: hosted, local, tiny, fake
./scripts/profile.ps1 claude -Voice   # also start the voice services
```

The script edits `MODEL_PROFILE` and `LITELLM_PROFILE` in `.env` and restarts LiteLLM, the API, the
worker and the web app. It works in Windows PowerShell 5.1.

**Cost limits for `claude`.** The app calls LiteLLM with its own key, created by the script, with a
daily budget (`CLAUDE_DAILY_BUDGET_USD`, default 5) and a request limit (`CLAUDE_RPM_LIMIT`, default
60 per minute) from `.env`. Once the budget is used, model calls fail until the next day (UTC).
LiteLLM counts cost with the prices in `config/litellm.claude.yaml`, in its own `litellm` database
(`infra/compose.claude.yaml`). Set a monthly spend limit in the Anthropic Console as well: it is
the hard limit, and it also covers anything outside this app.

Set `LITELLM_PROFILE` to the same value, so the proxy loads the matching `config/litellm.*.yaml`.
`./scripts/models.ps1` and `./scripts/latency.ps1` set both for you.
To point one role at another alias, such as LM Studio on the host, set
`MODEL_ROLE_<ROLE>=<alias>`, for example `MODEL_ROLE_INTERVIEWER=local-lmstudio`.

## Billing (Stripe, test mode)

The app runs without Stripe keys: the paywall then says payments are not set up. To check the
subscribe, use and cancel flow with the Stripe CLI, follow
`apps/api/src/strong_api/billing/README.md`. It lists the `STRIPE_*` and `BILLING_*` variables.

## Repository layout

```
apps/api        FastAPI service
apps/worker     Arq background workers
apps/voice      LiveKit Agents voice agent
apps/web        React + Vite + TypeScript front end
packages/core   strong_core: config, contracts, database models, migrations, model gateway, prompt loader
prompts/        Prompt templates, one folder per role
config/         Model and LiteLLM config per profile
schemas/        JSON Schemas generated from the contracts
profiles/       Company profile JSON files
evals/          Eval harness and fixtures
infra/          Docker Compose, Dockerfiles, Caddy
scripts/        dev.ps1, models.ps1 (pull, smoke), latency.ps1
```
