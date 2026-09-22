"""M5 AI contracts (QGIS-free): provider abstraction + planner shapes.

The AI is a planner/interpreter (AGENTS.md:2): it proposes structured
requirements and tool calls; it never executes, never classifies data,
never performs GIS math. All tool calls route through the governed
executor (AGENTS.md:3); unknown tools, malformed arguments, unsupported
versions, and unauthorized operations are rejected before execution.

Trust model (M4 §9 M5-must): untrusted segments (T2 layer metadata/
names, T3 provider metadata) are trust-LABELED and never concatenated
into system prompts unlabeled. Summaries-only consumption.

Privacy (AGENTS.md:10): API keys never appear in records, logs, audit
trails, or model context. Context assembly (``ai.context``) minimizes
what leaves the machine; the user can inspect exactly what is sent.

Stdlib only. No ``qgis.*``, no network clients (transport lives in
``ai.openrouter`` behind the same egress discipline as providers).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

AI_MODEL_VERSION = "1.0"

OPENROUTER_HOST = "openrouter.ai"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Default model (config-overridable; impl config, not a contract).
DEFAULT_MODEL = "openai/gpt-4o-mini"


class AIRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AIErrorCode(str, Enum):
    """Closed AI error taxonomy (distinguish, never collapse).

    Genuinely-unavailable (offline fallback applies): PROVIDER_OFFLINE,
    NETWORK_UNREACHABLE, TIMEOUT, SERVER_ERROR, RATE_LIMITED.
    Configuration/credential/content (hard error, no silent fallback):
    NO_API_KEY, AUTH_FAILED, ENDPOINT_NOT_FOUND, INVALID_REQUEST,
    INVALID_RESPONSE, MALFORMED_TOOL_CALL.
    """

    NO_API_KEY = "NO_API_KEY"
    AUTH_FAILED = "AUTH_FAILED"
    ENDPOINT_NOT_FOUND = "ENDPOINT_NOT_FOUND"
    INVALID_REQUEST = "INVALID_REQUEST"
    SERVER_ERROR = "SERVER_ERROR"
    NETWORK_UNREACHABLE = "NETWORK_UNREACHABLE"
    TLS_FAILED = "TLS_FAILED"
    PROVIDER_OFFLINE = "PROVIDER_OFFLINE"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    MALFORMED_TOOL_CALL = "MALFORMED_TOOL_CALL"
    UNSUPPORTED_TOOL_VERSION = "UNSUPPORTED_TOOL_VERSION"
    UNAUTHORIZED_OPERATION = "UNAUTHORIZED_OPERATION"


# Error classes for which the deterministic offline planner is a
# legitimate fallback (provider genuinely unreachable/transient).
# Auth/config/content errors must surface, never silently degrade.
OFFLINE_FALLBACK_ERRORS: frozenset[str] = frozenset(
    {
        AIErrorCode.PROVIDER_OFFLINE.value,
        AIErrorCode.NETWORK_UNREACHABLE.value,
        AIErrorCode.TLS_FAILED.value,
        AIErrorCode.TIMEOUT.value,
        AIErrorCode.SERVER_ERROR.value,
        AIErrorCode.RATE_LIMITED.value,
    }
)


class TrustLabel(str, Enum):
    """Provenance of a context segment (M4 §9 M5-must)."""

    TRUSTED_SYSTEM = "trusted-system"  # Lunar GIS prompt scaffolding
    TRUSTED_USER = "trusted-user"  # verbatim user request
    UNTRUSTED_PROJECT = "untrusted-project"  # T2: layer names/metadata
    UNTRUSTED_PROVIDER = "untrusted-provider"  # T3: catalog metadata
    ENGINE_OUTPUT = "engine-output"  # deterministic tool results


@dataclass(frozen=True)
class ContextSegment:
    """One labeled context segment. Labels are never stripped."""

    label: TrustLabel
    text: str

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("ContextSegment text must be non-empty")


@dataclass(frozen=True)
class AIMessage:
    role: AIRole
    content: str
    tool_calls: tuple[dict[str, Any], ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True)
class AIToolCall:
    """Validated structured tool call (planner output, pre-execution)."""

    tool_name: str
    tool_version: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class AIConfig:
    """AI configuration. The key is a runtime secret, never serialized."""

    model: str = DEFAULT_MODEL
    endpoint: str = OPENROUTER_API_URL
    timeout_s: float = 60.0
    max_tokens: int = 2000
    temperature: float = 0.2

    def public_dict(self) -> dict[str, Any]:
        """Serializable config WITHOUT secrets (safe for logs/settings UI)."""
        return {
            "model": self.model,
            "endpoint": self.endpoint,
            "timeout_s": self.timeout_s,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "api_key_configured": None,  # filled by the key holder, never here
        }


@dataclass(frozen=True)
class AIResponse:
    """Parsed model response: explanation + proposed tool calls."""

    explanation: str
    tool_calls: tuple[AIToolCall, ...] = ()
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanResult:
    """Planner outcome for one user request."""

    ok: bool
    explanation: str = ""
    requirement: dict[str, Any] | None = None
    tool_calls: tuple[AIToolCall, ...] = ()
    warnings: tuple[str, ...] = ()
    error: str = ""


def validate_tool_call_shape(call: dict[str, Any]) -> list[str]:
    """Validate the raw shape of a model-emitted tool call. Empty = valid."""
    errors: list[str] = []
    if not isinstance(call, dict):
        return ["tool call must be an object"]
    for key in ("tool_name", "arguments"):
        if key not in call:
            errors.append(f"tool call.{key}: required field missing")
    name = call.get("tool_name")
    if name is not None and (not isinstance(name, str) or "." not in name):
        errors.append("tool call.tool_name: must use dot notation")
    args = call.get("arguments")
    if args is not None and not isinstance(args, dict):
        errors.append("tool call.arguments: must be an object")
    version = call.get("tool_version", "1.0.0")
    if not isinstance(version, str) or len(version.split(".")) != 3:
        errors.append("tool call.tool_version: must be 'major.minor.patch'")
    return errors


__all__ = [
    "AI_MODEL_VERSION",
    "OPENROUTER_HOST",
    "OPENROUTER_API_URL",
    "DEFAULT_MODEL",
    "AIRole",
    "AIErrorCode",
    "OFFLINE_FALLBACK_ERRORS",
    "TrustLabel",
    "ContextSegment",
    "AIMessage",
    "AIToolCall",
    "AIConfig",
    "AIResponse",
    "PlanResult",
    "validate_tool_call_shape",
]
