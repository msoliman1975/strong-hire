# One image recipe for every Python service in the uv workspace.
#   docker build -f infra/docker/python.Dockerfile --build-arg PACKAGE=strong-api --build-arg APP_DIR=apps/api .
FROM python:3.12-slim

ARG PACKAGE
ARG APP_DIR

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_NATIVE_TLS=1 \
    PATH=/app/.venv/bin:$PATH

# Trust extra CA certificates from infra/certs/*.crt (networks with TLS inspection).
COPY infra/certs/ /tmp/certs/
RUN find /tmp/certs -name '*.crt' -exec cp {} /usr/local/share/ca-certificates/ \; \
    && update-ca-certificates >/dev/null \
    && rm -rf /tmp/certs

COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first, for layer caching. Every workspace member's pyproject is needed to resolve.
COPY pyproject.toml uv.lock .python-version ./
COPY packages/core/pyproject.toml packages/core/
COPY apps/api/pyproject.toml apps/api/
COPY apps/worker/pyproject.toml apps/worker/
COPY apps/voice/pyproject.toml apps/voice/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package ${PACKAGE} --no-install-workspace

COPY packages/core packages/core
COPY ${APP_DIR} ${APP_DIR}
COPY config config
COPY prompts prompts
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package ${PACKAGE}
