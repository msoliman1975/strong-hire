"""The MLflow trace server in the stack (LT-11, LT-12, LT-13): compose, Caddy, the sim server."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from strong_core.config import find_repo_root

REPO = find_repo_root()
INFRA = REPO / "infra"
BCRYPT = re.compile(r"^\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}$")


class _ComposeLoader(yaml.SafeLoader):
    """Reads compose files, including the !reset and !override merge tags."""


def _tagged(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)  # type: ignore[arg-type]


_ComposeLoader.add_constructor("!reset", _tagged)
_ComposeLoader.add_constructor("!override", _tagged)


def _compose(path: Path) -> dict[str, Any]:
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=_ComposeLoader)
    assert isinstance(data, dict)
    return data


def _dockerfile_version() -> str:
    text = (INFRA / "docker/mlflow.Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"^ARG MLFLOW_VERSION=(\d+\.\d+\.\d+)$", text, re.M)
    assert match, "mlflow.Dockerfile must pin MLFLOW_VERSION to an exact version"
    assert '"mlflow==${MLFLOW_VERSION}"' in text
    return match.group(1)


def _caddy_sites() -> dict[str, str]:
    """Top-level Caddyfile site blocks by address."""
    text = (INFRA / "caddy/Caddyfile").read_text(encoding="utf-8")
    sites: dict[str, str] = {}
    current: str | None = None
    depth = 0
    body: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if depth == 0 and stripped.endswith("{") and not stripped.startswith("#"):
            current, body = stripped[:-1].strip(), []
        if current is not None:
            body.append(line)
        depth += line.count("{") - line.count("}")
        if current is not None and depth == 0:
            sites[current] = "\n".join(body)
            current = None
    return sites


def _start_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mlflow_start", INFRA / "mlflow/start.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- LT-12: the service ------------------------------------------------------------------------


def test_lt12_local_service_is_opt_in_with_its_own_database() -> None:
    """LT-12: mlflow runs only in the obs profile, on the stack's Postgres, image pinned."""
    compose = _compose(INFRA / "compose.yaml")
    svc = compose["services"]["mlflow"]
    assert svc["profiles"] == ["obs"]
    assert svc["image"] == f"strong-mlflow:{_dockerfile_version()}"
    assert svc["build"]["dockerfile"] == "infra/docker/mlflow.Dockerfile"
    assert svc["environment"]["MLFLOW_DB"] == "mlflow"
    assert svc["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert "mlflow-artifacts:/mlflow/artifacts" in svc["volumes"]
    assert "mlflow-artifacts" in compose["volumes"]
    assert "mlflow,mlflow:5000" in svc["environment"]["MLFLOW_ALLOWED_HOSTS"]


def test_lt12_python_services_have_tracing_off_by_default() -> None:
    """LT-1, LT-12: every Python service gets the settings, with tracing off unless .env says."""
    env = _compose(INFRA / "compose.yaml")["x-python-env"]
    assert env["LLM_TRACING"] == "${LLM_TRACING:-off}"
    assert env["LLM_TRACING_DEV"] == "${LLM_TRACING_DEV:-off}"
    assert env["MLFLOW_TRACKING_URI"] == "${MLFLOW_TRACKING_URI:-http://mlflow:5000}"
    assert env["MLFLOW_EXPERIMENT"] == "${MLFLOW_EXPERIMENT:-dev}"


def test_lt12_server_service_is_capped_and_unpublished() -> None:
    """LT-12: on the server, no host port, 1 GB, and the public host name allowed."""
    svc = _compose(INFRA / "compose.server.yaml")["services"]["mlflow"]
    assert svc["ports"] == []
    assert svc["mem_limit"] == "1g"
    assert "mlflow.${DOMAIN}" in svc["environment"]["MLFLOW_ALLOWED_HOSTS"].split(",")


def test_lt12_server_never_traces_dev_sessions() -> None:
    """LT-3, LT-12: the server forces LLM_TRACING_DEV off for every app service."""
    services = _compose(INFRA / "compose.server.yaml")["services"]
    for name in ("api", "worker", "voice"):
        assert services[name]["environment"]["LLM_TRACING_DEV"] == "off", name


def test_lt12_server_sim_service_logs_to_the_local_mlflow() -> None:
    """LT-10, LT-12: admin sims reach MLflow inside the server network, in the sim experiment."""
    env = _compose(INFRA / "compose.server.yaml")["services"]["sim"]["environment"]
    assert env["MLFLOW_TRACKING_URI"] == "http://mlflow:5000"
    assert env["MLFLOW_EXPERIMENT"] == "${MLFLOW_EXPERIMENT:-sim}"
    assert env["LLM_TRACING"] == "${LLM_TRACING:-off}"


def test_lt12_caddy_site_is_behind_basic_auth() -> None:
    """LT-12: mlflow.$DOMAIN asks for a password; no other site proxies to mlflow."""
    sites = _caddy_sites()
    site = sites["mlflow.{$DOMAIN}"]
    assert "basic_auth {" in site
    assert "reverse_proxy mlflow:5000" in site
    assert "noindex" in site
    others = [
        addr for addr, body in sites.items() if addr != "mlflow.{$DOMAIN}" and "mlflow" in body
    ]
    assert not others, others


def test_lt12_default_password_hash_is_closed_and_consistent() -> None:
    """LT-12: with no hash in .env, Caddy still starts and the site stays closed."""
    site = _caddy_sites()["mlflow.{$DOMAIN}"]
    match = re.search(
        r"\{\$MLFLOW_BASIC_AUTH_USER:mlflow\} \{\$MLFLOW_BASIC_AUTH_HASH:([^}]+)\}", site
    )
    assert match, "basic_auth needs defaults so Caddy validates without the variables"
    default_hash = match.group(1)
    assert BCRYPT.match(default_hash)
    caddy_env = _compose(INFRA / "compose.server.yaml")["services"]["caddy"]["environment"]
    compose_default = (
        caddy_env["MLFLOW_BASIC_AUTH_HASH"]
        .removeprefix("${MLFLOW_BASIC_AUTH_HASH:-")
        .removesuffix("}")
    )
    assert compose_default.replace("$$", "$") == default_hash


def test_lt12_start_script_uses_psycopg3_and_the_host_guard() -> None:
    """LT-12: the launcher's server arguments: psycopg 3 store, artifacts volume, allowed hosts."""
    start = _start_module()
    import os

    old = os.environ.get("MLFLOW_ALLOWED_HOSTS")
    os.environ["MLFLOW_ALLOWED_HOSTS"] = "mlflow:5000"
    try:
        args = start.server_args("postgres", "u", "p", "mlflow")
    finally:
        if old is None:
            del os.environ["MLFLOW_ALLOWED_HOSTS"]
        else:
            os.environ["MLFLOW_ALLOWED_HOSTS"] = old
    assert args[:2] == ["mlflow", "server"]
    opts = dict(zip(args[2::2], args[3::2], strict=True))
    assert opts["--backend-store-uri"] == "postgresql+psycopg://u:p@postgres:5432/mlflow"
    assert opts["--artifacts-destination"] == "/mlflow/artifacts"
    assert opts["--allowed-hosts"] == "mlflow:5000"
    assert opts["--port"] == "5000"


def test_lt12_every_mlflow_pin_matches_the_server_image() -> None:
    """LT-12: mlflow-tracing (core), mlflow-skinny (sim) and the image use one version."""
    version = _dockerfile_version()
    pins: list[tuple[str, str]] = []
    for path in REPO.glob("**/pyproject.toml"):
        if ".venv" in path.parts or "node_modules" in path.parts:
            continue
        for found in re.findall(r'"mlflow(?:-tracing|-skinny)?==([^"]+)"', path.read_text()):
            pins.append((str(path.relative_to(REPO)), found))
    assert all(v == version for _, v in pins), pins


def test_lt12_ci_starts_the_trace_server() -> None:
    """LT-12: CI parses the obs profile and starts mlflow on a fresh Postgres."""
    ci = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "--profile voice --profile obs config --quiet" in ci
    assert "up -d --build --wait mlflow" in ci


# --- LT-11 and LT-13: scripts ------------------------------------------------------------------


def test_lt11_dev_ps1_has_the_obs_profile_and_prunes_dev_traces() -> None:
    """LT-11: up -Profile obs starts core with mlflow and deletes dev traces older than 30 days."""
    dev = (REPO / "scripts/dev.ps1").read_text(encoding="utf-8")
    assert "'obs' { @('core', 'obs') }" in dev
    assert "'strong_core.tracing', 'prune', '--experiment', 'dev', '--days', '30'" in dev
    profile = (REPO / "scripts/profile.ps1").read_text(encoding="utf-8")
    assert "(Get-EnvValues)['LLM_TRACING'] -eq 'on'" in profile


def test_lt13_sim_server_gets_credentials_only_when_set() -> None:
    """LT-13: the sim server logs to the main server's MLflow only with the optional secret."""
    env = _compose(INFRA / "sim/compose.sim.yaml")["services"]["sim"]["environment"]
    for key in ("MLFLOW_TRACKING_URI", "MLFLOW_TRACKING_USERNAME", "MLFLOW_TRACKING_PASSWORD"):
        assert env[key] == f"${{{key}:-}}"
    assert env["MLFLOW_EXPERIMENT"] == "sim"
    run = (INFRA / "sim/sim-run.ps1").read_text(encoding="utf-8")
    block = run[run.index("if ($mlflowPassword) {") :]
    block = block[: block.index("}")]
    assert '"MLFLOW_TRACKING_URI=https://mlflow.$mlflowDomain"' in block
    assert '"MLFLOW_TRACKING_PASSWORD=$mlflowPassword"' in block
    assert "Get-OptionalUserSecret 'STRONGHIRE_MLFLOW_PASSWORD'" in run
