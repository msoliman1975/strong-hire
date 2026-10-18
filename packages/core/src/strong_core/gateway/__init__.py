"""The model gateway: the only place in the codebase that calls models (PL-1)."""

from strong_core.gateway.client import GatewayError, ModelGateway, build_gateway, get_gateway
from strong_core.gateway.fake import FakeBackend, FakeFixtureMissingError
from strong_core.gateway.registry import (
    CapabilityTier,
    ModelCapabilities,
    ModelsConfig,
    load_models_config,
)
from strong_core.gateway.types import Completion, Message, Role, TokenUsage
from strong_core.gateway.usage import (
    UsageContext,
    UsageRecord,
    UsageSink,
    current_usage_context,
    db_usage_sink,
    get_usage_sink,
    make_db_usage_sink,
    set_usage_sink,
    usage_context,
)

__all__ = [
    "CapabilityTier",
    "Completion",
    "FakeBackend",
    "FakeFixtureMissingError",
    "GatewayError",
    "Message",
    "ModelCapabilities",
    "ModelGateway",
    "ModelsConfig",
    "Role",
    "TokenUsage",
    "UsageContext",
    "UsageRecord",
    "UsageSink",
    "build_gateway",
    "current_usage_context",
    "db_usage_sink",
    "get_gateway",
    "get_usage_sink",
    "load_models_config",
    "make_db_usage_sink",
    "set_usage_sink",
    "usage_context",
]
