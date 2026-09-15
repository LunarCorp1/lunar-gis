"""AHP tool adapter: thin boundary between M1 ToolContract and M2-T02 AHP engine.

This module provides the ToolSpec and handler for deterministic AHP
pairwise analysis. It translates validated ToolInput into the M2-T02 API
and translates AHPResult into ToolOutput.

The AHP mathematics remain in lunar_gis.analysis.ahp — this module
does not reimplement any calculation.

Public API:
  - AHP_TOOL_SPEC: ToolSpec for AHP pairwise analysis
  - ahp_handler(input_data: dict) -> dict: registered handler
  - register_ahp_tool(registry: ToolRegistry) -> None
"""

from __future__ import annotations

from typing import Any

from lunar_gis.agent.registry import (
    ToolRegistry,
    ToolRisk,
    ToolSpec,
    ToolVersion,
)
from lunar_gis.analysis.ahp import (
    AHPResult,
    ahp,
)


# ---------------------------------------------------------------------------
# ToolSpec
# ---------------------------------------------------------------------------

AHP_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "criteria": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "matrix": {
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "number"},
            },
        },
    },
    "required": ["criteria", "matrix"],
    "additionalProperties": False,
}

AHP_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "criteria": {"type": "array", "items": {"type": "string"}},
        "weights": {"type": "array", "items": {"type": "number"}},
        "weights_dict": {"type": "object"},
        "lambda_max": {"type": "number"},
        "ci": {"type": "number"},
        "ri": {"type": "number"},
        "ri_source": {"type": "string"},
        "cr": {"type": "number"},
        "consistency_flag": {"type": "string"},
        "trivial_consistency": {"type": "boolean"},
        "method": {"type": "string"},
        "engine_version": {"type": "string"},
        "numerical_policy_version": {"type": "string"},
        "input_hash": {"type": "string"},
        "iteration_count": {"type": "integer"},
    },
    "required": [
        "criteria",
        "weights",
        "lambda_max",
        "ci",
        "ri",
        "cr",
        "consistency_flag",
    ],
    "additionalProperties": False,
}

AHP_TOOL_SPEC = ToolSpec(
    name="analysis.ahp",
    version=ToolVersion(major=1, minor=0, patch=0),
    risk=ToolRisk.LOW,
    handler=None,  # set by register_ahp_tool
    input_schema=AHP_INPUT_SCHEMA,
    output_schema=AHP_OUTPUT_SCHEMA,
    description=(
        "Deterministic AHP pairwise comparison analysis. "
        "Computes priority weights, lambda-max, CI, CR, and consistency "
        "classification from a reciprocal pairwise comparison matrix."
    ),
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def ahp_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    """Handle AHP tool invocation.

    Translates ToolInput -> ahp() -> ToolOutput.
    Raises AHPError on invalid input or numerical failure — the
    ControlledExecutor converts this to a failed ToolResult.
    """
    criteria = list(input_data["criteria"])
    matrix = [list(row) for row in input_data["matrix"]]

    result: AHPResult = ahp(criteria, matrix)

    return {
        "criteria": list(result.criteria),
        "weights": list(result.weights),
        "weights_dict": result.weights_dict(),
        "lambda_max": result.consistency.lambda_max,
        "ci": result.consistency.ci,
        "ri": result.consistency.ri_value,
        "ri_source": result.consistency.ri_source,
        "cr": result.consistency.cr,
        "consistency_flag": result.consistency.flag.value,
        "trivial_consistency": result.consistency.trivial_consistency,
        "method": result.method,
        "engine_version": result.engine_version,
        "numerical_policy_version": result.numerical_policy_version,
        "input_hash": result.input_hash,
        "iteration_count": result.iteration_count,
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_ahp_tool(registry: ToolRegistry) -> None:
    """Register the AHP tool with its handler in the given registry."""
    spec = ToolSpec(
        name=AHP_TOOL_SPEC.name,
        version=AHP_TOOL_SPEC.version,
        risk=AHP_TOOL_SPEC.risk,
        handler=ahp_handler,
        input_schema=AHP_TOOL_SPEC.input_schema,
        output_schema=AHP_TOOL_SPEC.output_schema,
        description=AHP_TOOL_SPEC.description,
    )
    registry.register(spec)
