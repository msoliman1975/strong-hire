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
12. Optional, local models: `./scripts/dev.ps1 up -Profile models`, then pull a model with
    `docker compose -f infra/compose.yaml exec ollama ollama pull qwen2.5:3b-instruct`
    and set `MODEL_PROFILE=local` in `.env`.
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
| voice | voice agent | 8081 | Stub until P1 |
| voice | stt (faster-whisper) | 8010 | Stub until P1 |
| voice | tts (Kokoro) | 8880 | Stub until P1 |

## Model profiles

`MODEL_PROFILE` picks how the model gateway works:

- `fake`: recorded fixtures, no model. The default, and the only profile tests use.
- `local`: `config/models.local.yaml`, through LiteLLM to Ollama in Docker.
- `hosted`: `config/models.hosted.yaml`, through LiteLLM to hosted APIs. Needs provider keys in `.env`.

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
scripts/        dev.ps1
```
