"""M4-T04 governed transformation tool: data.run_transformation v1.

Thin boundary between the M1 tool contract and the §8 transformation
boundary. Translates validated ToolInput (TransformationStep[]) into
``transform_qgis.run_chain`` and translates the chain result into
ToolOutput.

GIS math stays in QGIS/Processing; step declaration/validation stays in
``transforms`` (QGIS-free). This module resolves the live project via a
deferred import (fail-closed outside QGIS) and never touches the
network, eval, or subprocess.

Public API:
- RUN_TRANSFORMATION_TOOL_SPEC: ToolSpec (HIGH risk, confirmation-gated)
- run_transformation_handler(input_data: dict) -> dict
- register_transformation_tool(registry: ToolRegistry) -> None
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

from lunar_gis.agent.registry import (
    ToolRegistry,
    ToolRisk,
    ToolSpec,
    ToolVersion,
)
from lunar_gis.data.transforms import TRANSFORM_MODEL_VERSION, validate_chain

RUN_TRANSFORMATION_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {"type": "object"},
        },
        "workspace_dir": {"type": "string"},
    },
    "required": ["steps"],
    "additionalProperties": False,
}

RUN_TRANSFORMATION_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "outputs": {"type": "array", "items": {"type": "object"}},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "error": {"type": "string"},
        "sandbox_dir": {"type": "string"},
        "transform_model_version": {"type": "string"},
    },
    "required": ["ok", "outputs", "evidence", "transform_model_version"],
    "additionalProperties": False,
}

RUN_TRANSFORMATION_TOOL_SPEC = ToolSpec(
    name="data.run_transformation",
    version=ToolVersion(major=1, minor=0, patch=0),
    risk=ToolRisk.HIGH,
    handler=None,  # set by register_transformation_tool
    input_schema=RUN_TRANSFORMATION_INPUT_SCHEMA,
    output_schema=RUN_TRANSFORMATION_OUTPUT_SCHEMA,
    description=(
        "Execute a declared §8 transformation chain via QGIS Processing. "
        "HIGH risk: destructive/expensive — requires explicit confirmation."
    ),
)


def _resolve_project() -> Any | None:
    try:
        from qgis.core import QgsProject  # type: ignore[import-not-found]

        return QgsProject.instance()
    except ImportError:
        return None


def run_transformation_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    """Execute a validated transformation chain. Never raises."""
    from lunar_gis.data.transform_qgis import run_chain

    steps = input_data.get("steps", [])
    if not isinstance(steps, list):
        return {
            "ok": False,
            "outputs": [],
            "evidence": [],
            "error": "steps must be an array",
            "transform_model_version": TRANSFORM_MODEL_VERSION,
        }
    errors = validate_chain(steps)
    if errors:
        return {
            "ok": False,
            "outputs": [],
            "evidence": [],
            "error": f"invalid chain: {'; '.join(errors)}",
            "transform_model_version": TRANSFORM_MODEL_VERSION,
        }
    workspace = input_data.get("workspace_dir")
    sandbox_dir: str | None = None
    if isinstance(workspace, str) and workspace and os.path.isdir(workspace):
        try:
            sandbox_dir = tempfile.mkdtemp(prefix="lunar-transform-", dir=workspace)
        except OSError:
            sandbox_dir = None
    project = _resolve_project()
    try:
        result = run_chain(steps, project=project, sandbox_dir=sandbox_dir)
    except Exception as exc:  # fail-closed: never leak tracebacks to tool output
        result = {
            "ok": False,
            "outputs": [],
            "evidence": [],
            "error": f"transformation failed: {type(exc).__name__}",
        }
    result["transform_model_version"] = TRANSFORM_MODEL_VERSION
    if sandbox_dir is not None:
        result["sandbox_dir"] = sandbox_dir
    return result


def register_transformation_tool(registry: ToolRegistry) -> None:
    """Register data.run_transformation v1 with its handler."""
    registry.register(
        ToolSpec(
            name=RUN_TRANSFORMATION_TOOL_SPEC.name,
            version=RUN_TRANSFORMATION_TOOL_SPEC.version,
            risk=RUN_TRANSFORMATION_TOOL_SPEC.risk,
            handler=run_transformation_handler,
            input_schema=RUN_TRANSFORMATION_INPUT_SCHEMA,
            output_schema=RUN_TRANSFORMATION_OUTPUT_SCHEMA,
            description=RUN_TRANSFORMATION_TOOL_SPEC.description,
        )
    )


__all__ = [
    "RUN_TRANSFORMATION_TOOL_SPEC",
    "run_transformation_handler",
    "register_transformation_tool",
]
