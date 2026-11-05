# MLflow tracking server for LLM traces (LT-12, docs/llm-tracing/spec.md).
# The version must match mlflow-tracing in packages/core and mlflow-skinny in apps/sim.
# The official image has no Postgres driver, so this one adds psycopg 3 (the repo's driver).
# Build context: the repo root.
FROM python:3.12-slim

# Trust extra CA certificates from infra/certs/*.crt (networks with TLS inspection).
COPY infra/certs/ /tmp/certs/
RUN cat /etc/ssl/certs/ca-certificates.crt /tmp/certs/*.crt > /usr/local/share/ca-bundle.pem 2>/dev/null || true; rm -rf /tmp/certs
ENV PIP_CERT=/usr/local/share/ca-bundle.pem \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    MLFLOW_DISABLE_TELEMETRY=true \
    DO_NOT_TRACK=1

ARG MLFLOW_VERSION=3.17.2
RUN pip install --quiet "mlflow==${MLFLOW_VERSION}" "psycopg[binary]==3.3.6"

COPY infra/mlflow/start.py /opt/mlflow/start.py
RUN mkdir -p /mlflow/artifacts
EXPOSE 5000
CMD ["python", "/opt/mlflow/start.py"]
