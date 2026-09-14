"""Foundational tool registry contracts. No AI execution is implemented yet."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


# ---------------------------------------------------------------------------
# ToolRisk
# ---------------------------------------------------------------------------


class ToolRisk(Enum):
    """Risk classification for tool execution.

    Must remain aligned with AGENTS.md rules and the existing risk model.
    """

    READ = "read"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ---------------------------------------------------------------------------
# ToolVersion
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class ToolVersion:
    """Semantic-ish version for tool schema versioning.

    Supports deterministic comparison and JSON-compatible serialization.
    """

    major: int = 0
    minor: int = 0
    patch: int = 1

    def __post_init__(self) -> None:
        for attr in ("major", "minor", "patch"):
            val = getattr(self, attr)
            if not isinstance(val, int) or val < 0:
                raise ValueError(f"ToolVersion.{attr} must be a non-negative integer, got {val!r}")

    def to_tuple(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def to_str(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def from_str(cls, s: str) -> ToolVersion:
        parts = s.split(".")
        if len(parts) != 3:
            raise ValueError(f"ToolVersion string must be 'major.minor.patch', got {s!r}")
        try:
            return cls(major=int(parts[0]), minor=int(parts[1]), patch=int(parts[2]))
        except ValueError:
            raise ValueError(f"ToolVersion string parts must be integers, got {s!r}") from None

    def to_dict(self) -> dict[str, int]:
        return {"major": self.major, "minor": self.minor, "patch": self.patch}


# ---------------------------------------------------------------------------
# Schema validation (minimal, no jsonschema dependency)
# ---------------------------------------------------------------------------

_SUPPORTED_TYPES = {"string", "number", "integer", "boolean", "array", "object", "null"}


def _validate_schema_type(value: Any, expected_type: str, path: str) -> list[str]:
    """Validate a single value against a schema type string."""
    errors: list[str] = []
    if expected_type == "string":
        if not isinstance(value, str):
            errors.append(f"{path}: expected string, got {type(value).__name__}")
    elif expected_type == "number":
        if not isinstance(value, (int, float)):
            errors.append(f"{path}: expected number, got {type(value).__name__}")
    elif expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"{path}: expected integer, got {type(value).__name__}")
    elif expected_type == "boolean":
        if not isinstance(value, bool):
            errors.append(f"{path}: expected boolean, got {type(value).__name__}")
    elif expected_type == "array":
        if not isinstance(value, list):
            errors.append(f"{path}: expected array, got {type(value).__name__}")
    elif expected_type == "object":
        if not isinstance(value, dict):
            errors.append(f"{path}: expected object, got {type(value).__name__}")
    elif expected_type == "null":
        if value is not None:
            errors.append(f"{path}: expected null, got {type(value).__name__}")
    else:
        errors.append(f"{path}: unsupported schema type {expected_type!r}")
    return errors


def _validate_data_against_schema(data: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Validate data against a simplified JSON-Schema-like definition.

    Supports: type, properties, required, additionalProperties, items (for arrays).
    """
    errors: list[str] = []

    if "type" in schema:
        errors.extend(_validate_schema_type(data, schema["type"], path))

    if "properties" in schema and isinstance(data, dict):
        properties: dict[str, Any] = schema["properties"]
        required: list[str] = schema.get("required", [])
        additional = schema.get("additionalProperties", True)

        for field_name in required:
            if field_name not in data:
                errors.append(f"{path}.{field_name}: required field missing")

        if additional is False:
            allowed = set(properties.keys())
            for key in data:
                if key not in allowed:
                    errors.append(f"{path}.{key}: unexpected field (additionalProperties: false)")

        for key, value in data.items():
            if key in properties:
                errors.extend(_validate_data_against_schema(value, properties[key], f"{path}.{key}"))

    if "items" in schema and isinstance(data, list):
        item_schema: dict[str, Any] = schema["items"]
        for i, item in enumerate(data):
            errors.extend(_validate_data_against_schema(item, item_schema, f"{path}[{i}]"))

    return errors


def validate_input_schema(schema: dict[str, Any]) -> list[str]:
    """Validate that a tool input schema definition is well-formed."""
    errors: list[str] = []
    if not isinstance(schema, dict):
        return ["Input schema must be a dict"]

    if "type" in schema and schema["type"] != "object":
        errors.append("Input schema top-level type must be 'object'")

    if "properties" in schema:
        for name, prop in schema["properties"].items():
            if not isinstance(prop, dict):
                errors.append(f"Input schema property {name!r} must be a dict")
                continue
            if "type" in prop and prop["type"] not in _SUPPORTED_TYPES:
                errors.append(f"Input schema property {name!r} has unsupported type {prop['type']!r}")
            if "additionalProperties" in prop and isinstance(prop["additionalProperties"], dict):
                pass  # nested schemas are allowed

    if "required" in schema:
        if not isinstance(schema["required"], list):
            errors.append("Input schema 'required' must be a list")
        elif "properties" in schema:
            for req in schema["required"]:
                if req not in schema["properties"]:
                    errors.append(f"Input schema 'required' lists unknown property {req!r}")

    return errors


def validate_output_schema(schema: dict[str, Any]) -> list[str]:
    """Validate that a tool output schema definition is well-formed."""
    errors: list[str] = []
    if not isinstance(schema, dict):
        return ["Output schema must be a dict"]

    if "type" in schema and schema["type"] not in _SUPPORTED_TYPES:
        errors.append(f"Output schema top-level type has unsupported type {schema['type']!r}")

    if "properties" in schema:
        if not isinstance(schema["properties"], dict):
            errors.append("Output schema 'properties' must be a dict")
        else:
            for name, prop in schema["properties"].items():
                if not isinstance(prop, dict):
                    errors.append(f"Output schema property {name!r} must be a dict")
                    continue
                if "type" in prop and prop["type"] not in _SUPPORTED_TYPES:
                    errors.append(f"Output schema property {name!r} has unsupported type {prop['type']!r}")

    return errors


# ---------------------------------------------------------------------------
# ToolInput
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolInput:
    """Validated structured input for a tool.

    Input is a plain dict of JSON-compatible values. The schema is validated
    at construction time. No executable code is permitted.
    """

    data: dict[str, Any]
    schema: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.data, dict):
            raise TypeError(f"ToolInput.data must be a dict, got {type(self.data).__name__}")
        if self.schema:
            schema_errors = validate_input_schema(self.schema)
            if schema_errors:
                raise ValueError(f"Invalid input schema: {'; '.join(schema_errors)}")
            data_errors = _validate_data_against_schema(self.data, self.schema)
            if data_errors:
                raise ValueError(f"Input validation failed: {'; '.join(data_errors)}")
        _reject_non_json_values(self.data, "ToolInput.data")

    def to_dict(self) -> dict[str, Any]:
        return {"data": self.data, "schema": self.schema}


# ---------------------------------------------------------------------------
# ToolOutput
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolOutput:
    """Structured tool output.

    JSON-compatible data only. No implicit execution, no arbitrary objects.
    """

    data: dict[str, Any]
    schema: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.data, dict):
            raise TypeError(f"ToolOutput.data must be a dict, got {type(self.data).__name__}")
        if self.schema:
            schema_errors = validate_output_schema(self.schema)
            if schema_errors:
                raise ValueError(f"Invalid output schema: {'; '.join(schema_errors)}")
        _reject_non_json_values(self.data, "ToolOutput.data")

    def to_dict(self) -> dict[str, Any]:
        return {"data": self.data, "schema": self.schema}


# ---------------------------------------------------------------------------
# ToolExecutionContext
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolExecutionContext:
    """Minimal context for future tool execution.

    Contains only metadata appropriate for the contract layer.
    Does NOT contain API keys, secrets, credentials, filesystem access,
    network access, iface, QTimer, QgsTask, or executable Python source.
    """

    project_path: str | None = None
    qgis_version: str | None = None
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_path": self.project_path,
            "qgis_version": self.qgis_version,
            "session_id": self.session_id,
        }


# ---------------------------------------------------------------------------
# ToolResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolResult:
    """Result of a future tool invocation.

    Distinguishes success from failure with structured output.
    Exceptions and arbitrary Python objects must not cross the boundary.
    """

    success: bool
    output: ToolOutput | None = None
    error: str | None = None
    tool_name: str | None = None
    tool_version: ToolVersion | None = None

    def __post_init__(self) -> None:
        if not self.success and not self.error:
            raise ValueError("A failed ToolResult must include an error message")
        if self.success and self.error:
            raise ValueError("A successful ToolResult must not include an error message")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"success": self.success}
        if self.output is not None:
            result["output"] = self.output.to_dict()
        if self.error is not None:
            result["error"] = self.error
        if self.tool_name is not None:
            result["tool_name"] = self.tool_name
        if self.tool_version is not None:
            result["tool_version"] = self.tool_version.to_dict()
        return result


# ---------------------------------------------------------------------------
# ToolSpec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    """Hardened tool specification.

    Metadata and validation infrastructure only. Not an executor.
    The handler is stored for future execution layers; it is NOT called
    during registration or lookup.
    """

    name: str
    version: ToolVersion
    risk: ToolRisk
    handler: Callable[..., Any] | None = None
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValueError("ToolSpec.name must be a non-empty string")
        if "." not in self.name:
            raise ValueError(f"ToolSpec.name must use dot notation (e.g. 'project.list_layers'), got {self.name!r}")
        if not isinstance(self.version, ToolVersion):
            raise TypeError(f"ToolSpec.version must be a ToolVersion, got {type(self.version).__name__}")
        if not isinstance(self.risk, ToolRisk):
            raise TypeError(f"ToolSpec.risk must be a ToolRisk, got {type(self.risk).__name__}")
        if self.input_schema:
            errors = validate_input_schema(self.input_schema)
            if errors:
                raise ValueError(f"Invalid input_schema: {'; '.join(errors)}")
        if self.output_schema:
            errors = validate_output_schema(self.output_schema)
            if errors:
                raise ValueError(f"Invalid output_schema: {'; '.join(errors)}")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "version": self.version.to_dict(),
            "risk": self.risk.value,
            "description": self.description,
        }
        if self.input_schema:
            result["input_schema"] = self.input_schema
        if self.output_schema:
            result["output_schema"] = self.output_schema
        return result


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Metadata and validation infrastructure for tool registration.

    Not an executor. Does not call handlers, execute Python, make network
    requests, access QGIS GUI, download files, invoke an LLM, or interpret
    natural-language instructions.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if not isinstance(spec, ToolSpec):
            raise TypeError(f"Expected ToolSpec, got {type(spec).__name__}")
        if spec.name in self._tools:
            existing = self._tools[spec.name]
            raise ValueError(
                f"Tool already registered: {spec.name} (v{existing.version.to_str()} "
                f"cannot be overwritten by v{spec.version.to_str()})"
            )
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(f"Unknown tool: {name}") from None

    def has(self, name: str) -> bool:
        return name in self._tools

    def remove(self, name: str) -> ToolSpec:
        try:
            return self._tools.pop(name)
        except KeyError:
            raise KeyError(f"Unknown tool: {name}") from None

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def all_specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._tools[name] for name in self.names())

    def validate_spec(self, spec: ToolSpec) -> list[str]:
        """Validate a ToolSpec without registering it. Returns list of errors (empty = valid)."""
        errors: list[str] = []
        try:
            if not spec.name or not isinstance(spec.name, str):
                errors.append("name must be a non-empty string")
            if "." not in spec.name:
                errors.append(f"name must use dot notation, got {spec.name!r}")
        except Exception:
            errors.append("name is invalid")
        if not isinstance(spec.version, ToolVersion):
            errors.append("version must be a ToolVersion")
        if not isinstance(spec.risk, ToolRisk):
            errors.append("risk must be a ToolRisk")
        if spec.input_schema:
            errors.extend(validate_input_schema(spec.input_schema))
        if spec.output_schema:
            errors.extend(validate_output_schema(spec.output_schema))
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {name: self._tools[name].to_dict() for name in self.names()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reject_non_json_values(obj: Any, path: str) -> None:
    """Raise if obj contains non-JSON-serializable values."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise ValueError(f"{path}: dict keys must be strings, got {type(key).__name__}")
            _reject_non_json_values(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _reject_non_json_values(item, f"{path}[{i}]")
    elif not isinstance(obj, (str, int, float, bool, type(None))):
        raise ValueError(f"{path}: value must be JSON-compatible, got {type(obj).__name__}")
