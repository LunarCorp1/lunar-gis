"""M5 tool-calling bridge: registry validation → governed execution.

The model proposes; the registry disposes. Every model-emitted call is
validated BEFORE execution:

- unknown tool → UNKNOWN_TOOL (rejected)
- malformed shape → MALFORMED_TOOL_CALL (rejected)
- version mismatch vs registered spec → UNSUPPORTED_TOOL_VERSION
- arguments failing the ToolSpec input schema → rejected with reasons
- permission DENY → UNAUTHORIZED_OPERATION (confirmation cannot override)

Validated calls execute through ``ControlledExecutor`` (12-step
lifecycle, intent + terminal audit). This module never calls handlers
directly and never interprets natural language.
"""

from __future__ import annotations

from typing import Any

from lunar_gis.agent.execution import ControlledExecutor
from lunar_gis.agent.registry import ToolExecutionContext, ToolInput, ToolRegistry, ToolVersion
from lunar_gis.ai.contracts import AIErrorCode, validate_tool_call_shape


def validate_call_against_registry(call: dict[str, Any], registry: ToolRegistry) -> tuple[bool, dict[str, Any]]:
    """Validate one model-emitted call against the registry. (ok, info)."""
    shape_errors = validate_tool_call_shape(call)
    if shape_errors:
        return False, {"error": AIErrorCode.MALFORMED_TOOL_CALL.value, "detail": "; ".join(shape_errors)}
    name = call["tool_name"]
    if not registry.has(name):
        return False, {"error": AIErrorCode.UNKNOWN_TOOL.value, "detail": name}
    spec = registry.get(name)
    requested = call.get("tool_version", "1.0.0")
    try:
        requested_version = ToolVersion.from_str(requested)
    except ValueError:
        return False, {"error": AIErrorCode.UNSUPPORTED_TOOL_VERSION.value, "detail": requested}
    if requested_version.to_tuple() != spec.version.to_tuple():
        return False, {
            "error": AIErrorCode.UNSUPPORTED_TOOL_VERSION.value,
            "detail": f"requested {requested}, registered {spec.version.to_str()}",
        }
    arguments = call.get("arguments", {})
    try:
        ToolInput(data=arguments, schema=spec.input_schema if spec.input_schema else {})
    except (TypeError, ValueError) as exc:
        return False, {"error": AIErrorCode.MALFORMED_TOOL_CALL.value, "detail": str(exc)[:300]}
    return True, {"tool_name": name, "tool_version": requested}


def execute_validated_calls(
    calls: list[dict[str, Any]],
    registry: ToolRegistry,
    executor: ControlledExecutor,
    context: ToolExecutionContext,
    confirmations: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Validate then execute each call. Returns per-call result dicts."""
    results: list[dict[str, Any]] = []
    confirmations = confirmations or {}
    for call in calls:
        ok, info = validate_call_against_registry(call, registry)
        if not ok:
            results.append({"ok": False, "tool_name": call.get("tool_name", "?"), **info})
            continue
        confirmation = confirmations.get(info["tool_name"])
        try:
            result = executor.execute(info["tool_name"], call.get("arguments", {}), context, confirmation)
        except Exception as exc:
            results.append(
                {"ok": False, "tool_name": info["tool_name"], "error": f"execution-failed: {type(exc).__name__}"}
            )
            continue
        results.append(
            {
                "ok": result.success,
                "tool_name": info["tool_name"],
                "output": result.output.to_dict() if result.output is not None else None,
                "error": result.error,
            }
        )
    return results


def registry_tool_schemas(registry: ToolRegistry) -> list[dict[str, Any]]:
    """Tool schemas for the model (name/version/description/input only).

    Output schemas and handlers are never exposed to the model.
    """
    schemas: list[dict[str, Any]] = []
    for spec in registry.all_specs():
        schemas.append(
            {
                "name": spec.name,
                "version": spec.version.to_str(),
                "description": spec.description,
                "input_schema": spec.input_schema,
            }
        )
    return schemas


def to_provider_name(tool_name: str) -> str:
    """Registry dotted name → provider-safe function name.

    OpenAI-style function names must match ``^[a-zA-Z0-9_-]+$`` (no
    dots). The first dot becomes the first underscore; the registry
    side never changes.
    """
    if "." not in tool_name:
        raise ValueError(f"Tool name must use dot notation, got {tool_name!r}")
    return tool_name.replace(".", "_", 1)


def from_provider_name(provider_name: str, known_names: list[str]) -> str | None:
    """Provider-safe name → registry dotted name (None if unmapped).

    Reversal splits at the FIRST underscore (domains contain no
    underscores/dots by ToolSpec construction) and verifies against
    the known registry names — never guessed.
    """
    for name in known_names:
        try:
            if to_provider_name(name) == provider_name:
                return name
        except ValueError:
            continue
    return None


def extract_text_calls(text: str, known_names: list[str]) -> list[dict[str, Any]]:
    """Extract strictly-shaped fenced tool calls from model prose.

    Accepted shape only (no lenient parsing, no guessing)::

        ```json {"tool": "<dotted.or_wire.name>", "arguments": {...}} ```

    or with ``"tool_name"`` instead of ``"tool"``. Names map through the
    provider→registry table; unmapped names are dropped. Everything else
    (pseudo-code, unquoted keys, prose) is ignored. Returned calls still
    require ``validate_call_against_registry`` before execution.
    """
    import json as json_module
    import re

    calls: list[dict[str, Any]] = []
    for match in re.finditer(r"```json\s*(\{.*?\})\s*```", text or "", re.DOTALL):
        try:
            payload = json_module.loads(match.group(1))
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        raw_name = payload.get("tool", payload.get("tool_name", ""))
        arguments = payload.get("arguments", {})
        if not isinstance(raw_name, str) or not isinstance(arguments, dict):
            continue
        name = raw_name
        if name.startswith("functions."):
            name = name[len("functions.") :]
        if "." not in name:
            mapped = from_provider_name(name, known_names)
            if mapped is None:
                continue
            name = mapped
        if name not in known_names:
            continue
        calls.append({"tool_name": name, "tool_version": "1.0.0", "arguments": arguments})
    return calls


def build_provider_tools(schemas: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Build OpenAI-style tools + provider→registry name map.

    Raises ValueError on unmappable names or provider-name collisions
    (fail-closed: a collision would misroute a tool call).
    """
    tools: list[dict[str, Any]] = []
    mapping: dict[str, str] = {}
    for schema in schemas:
        name = schema["name"]
        provider_name = to_provider_name(name)
        if provider_name in mapping:
            raise ValueError(f"Provider tool-name collision: {provider_name!r}")
        mapping[provider_name] = name
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": provider_name,
                    "description": schema.get("description", ""),
                    "parameters": schema.get("input_schema", {"type": "object"}),
                },
            }
        )
    return tools, mapping


__all__ = [
    "validate_call_against_registry",
    "execute_validated_calls",
    "registry_tool_schemas",
    "to_provider_name",
    "from_provider_name",
    "extract_text_calls",
    "build_provider_tools",
]
