# The AI candidate (P13). Runs only on the short-lived sim server, never in the product stack.
#   docker compose -f infra/sim/compose.sim.yaml build sim
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_NATIVE_TLS=1 \
    PATH=/app/.venv/bin:$PATH

# ffmpeg writes the Ogg Opus recordings; rsync and ssh upload each finished session.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg rsync openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first, for layer caching. Every workspace member's pyproject is needed to resolve.
COPY pyproject.toml uv.lock .python-version ./
COPY packages/core/pyproject.toml packages/core/
COPY packages/interview/pyproject.toml packages/interview/
COPY apps/api/pyproject.toml apps/api/
COPY apps/worker/pyproject.toml apps/worker/
COPY apps/voice/pyproject.toml apps/voice/
COPY apps/sim/pyproject.toml apps/sim/
COPY evals/pyproject.toml evals/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package strong-sim --no-install-workspace

COPY packages/core packages/core
COPY packages/interview packages/interview
COPY apps/sim apps/sim
COPY config config
COPY prompts prompts
COPY evals/config evals/config
COPY evals/fixtures/inputs evals/fixtures/inputs
COPY evals/scenarios evals/scenarios
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package strong-sim

ENTRYPOINT ["strong-sim"]
CMD ["suites"]
