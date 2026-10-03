"""The model gateway: the only place in the codebase that calls models (PL-1)."""

from strong_core.gateway.client import GatewayError, ModelGateway, build_gateway, get_gateway
from strong_core.gateway.fake import FakeBackend, FakeFixtureMissingError
from strong_core.gateway.registry import ModelCapabilities, ModelsConfig, load_models_config
from strong_core.gateway.types import Completion, Message, Role, TokenUsage

__all__ = [
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
    "build_gateway",
    "get_gateway",
    "load_models_config",
]
