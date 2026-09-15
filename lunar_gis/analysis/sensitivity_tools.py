"""Sensitivity tool adapter: thin boundary between M1 ToolContract and M3-T01 sensitivity engine.

This module provides the ToolSpec and handler for deterministic AHP
sensitivity analysis. It translates validated ToolInput into the M3-T01 API
and translates SensitivityResult into ToolOutput.

The sensitivity mathematics remain in lunar_gis.analysis.sensitivity — this
module does not reimplement any calculation.

Public API:
  - SENSITIVITY_TOOL_SPEC: ToolSpec for AHP sensitivity analysis
  - sensitivity_handler(input_data: dict) -> dict: registered handler
  - register_sensitivity_tool(registry: ToolRegistry) -> None
"""

from __future__ import annotations

from typing import Any

from lunar_gis.agent.registry import (
    ToolRegistry,
    ToolRisk,
    ToolSpec,
    ToolVersion,
)
from lunar_gis.analysis.sensitivity import (
    SensitivityResult,
    sensitivity_ahp,
)


# ---------------------------------------------------------------------------
# ToolSpec
# ---------------------------------------------------------------------------

SENSITIVITY_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "criteria": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
        },
        "matrix": {
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "number"},
            },
        },
        "method": {
            "type": "string",
            "enum": ["OAT_WEIGHT", "OAT_PAIRWISE"],
        },
        "perturbation_range": {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 2,
            "maxItems": 2,
        },
        "num_steps": {
            "type": "integer",
            "minimum": 5,
            "maximum": 100,
        },
        "target_criteria": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["criteria", "matrix"],
    "additionalProperties": False,
}

SENSITIVITY_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "criteria": {"type": "array", "items": {"type": "string"}},
        "baseline_weights": {"type": "array", "items": {"type": "number"}},
        "baseline_ranking": {"type": "array", "items": {"type": "integer"}},
        "criterion_results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "criterion": {"type": "string"},
                    "baseline_weight": {"type": "number"},
                    "stability_lower": {"type": "number"},
                    "stability_upper": {"type": "number"},
                    "crossover_points": {"type": "array", "items": {"type": "number"}},
                    "perturbation_values": {"type": "array", "items": {"type": "number"}},
                    "perturbed_weights": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "number"}},
                    },
                    "perturbed_rankings": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "integer"}},
                    },
                    "consistency_flags": {"type": "array", "items": {"type": "string"}},
                    "consistency_ratios": {"type": "array", "items": {"type": "number"}},
                },
            },
        },
        "method": {"type": "string"},
        "sensitivity_policy_version": {"type": "string"},
        "numerical_policy_version": {"type": "string"},
        "engine_version": {"type": "string"},
        "input_hash": {"type": "string"},
        "perturbation_range": {"type": "array", "items": {"type": "number"}},
        "num_steps": {"type": "integer"},
        "target_criteria": {"type": "array", "items": {"type": "string"}},
        "ranking_policy_version": {"type": "string"},
        "consistency_policy_version": {"type": "string"},
        "near_ties": {
            "type": "array",
            "items": {"type": "array", "items": {"type": "string"}},
        },
    },
    "required": [
        "criteria",
        "baseline_weights",
        "baseline_ranking",
        "criterion_results",
        "method",
        "sensitivity_policy_version",
        "numerical_policy_version",
        "engine_version",
        "input_hash",
        "perturbation_range",
        "num_steps",
        "ranking_policy_version",
        "consistency_policy_version",
    ],
    "additionalProperties": False,
}

SENSITIVITY_TOOL_SPEC = ToolSpec(
    name="analysis.ahp_sensitivity",
    version=ToolVersion(major=1, minor=0, patch=0),
    risk=ToolRisk.LOW,
    handler=None,  # set by register_sensitivity_tool
    input_schema=SENSITIVITY_INPUT_SCHEMA,
    output_schema=SENSITIVITY_OUTPUT_SCHEMA,
    description=(
        "Deterministic AHP sensitivity analysis. Performs OAT weight "
        "perturbation to compute stability intervals, crossover points, "
        "and perturbed ranking scenarios for each criterion."
    ),
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def sensitivity_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    """Handle sensitivity tool invocation.

    Translates ToolInput -> sensitivity_ahp() -> ToolOutput.
    Raises SensitivityError on invalid input — the ControlledExecutor
    converts this to a failed ToolResult.
    """
    criteria = list(input_data["criteria"])
    matrix = [list(row) for row in input_data["matrix"]]

    kwargs: dict[str, Any] = {}
    if "method" in input_data:
        kwargs["method"] = input_data["method"]
    if "perturbation_range" in input_data:
        kwargs["perturbation_range"] = tuple(input_data["perturbation_range"])
    if "num_steps" in input_data:
        kwargs["num_steps"] = input_data["num_steps"]
    if "target_criteria" in input_data:
        kwargs["target_criteria"] = list(input_data["target_criteria"])

    result: SensitivityResult = sensitivity_ahp(criteria, matrix, **kwargs)

    return _serialize_result(result)


def _serialize_result(result: SensitivityResult) -> dict[str, Any]:
    """Serialize SensitivityResult into a JSON-compatible dict.

    Preserves all fields without silently discarding information.
    """
    criterion_results = []
    for cr in result.criterion_results:
        criterion_results.append(
            {
                "criterion": cr.criterion,
                "baseline_weight": cr.baseline_weight,
                "stability_lower": cr.stability_lower,
                "stability_upper": cr.stability_upper,
                "crossover_points": list(cr.crossover_points),
                "perturbation_values": list(cr.perturbation_values),
                "perturbed_weights": [list(w) for w in cr.perturbed_weights],
                "perturbed_rankings": [list(r) for r in cr.perturbed_rankings],
                "consistency_flags": list(cr.consistency_flags),
                "consistency_ratios": list(cr.consistency_ratios),
            }
        )

    output: dict[str, Any] = {
        "criteria": list(result.criteria),
        "baseline_weights": list(result.baseline_weights),
        "baseline_ranking": list(result.baseline_ranking),
        "criterion_results": criterion_results,
        "method": result.method.value,
        "sensitivity_policy_version": result.sensitivity_policy_version,
        "numerical_policy_version": result.numerical_policy_version,
        "engine_version": result.engine_version,
        "input_hash": result.input_hash,
        "perturbation_range": list(result.perturbation_range),
        "num_steps": result.num_steps,
        "ranking_policy_version": result.ranking_policy_version,
        "consistency_policy_version": result.consistency_policy_version,
        "near_ties": [list(pair) for pair in result.near_ties],
    }

    if result.target_criteria is not None:
        output["target_criteria"] = list(result.target_criteria)

    return output


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_sensitivity_tool(registry: ToolRegistry) -> None:
    """Register the sensitivity tool with its handler in the given registry."""
    spec = ToolSpec(
        name=SENSITIVITY_TOOL_SPEC.name,
        version=SENSITIVITY_TOOL_SPEC.version,
        risk=SENSITIVITY_TOOL_SPEC.risk,
        handler=sensitivity_handler,
        input_schema=SENSITIVITY_TOOL_SPEC.input_schema,
        output_schema=SENSITIVITY_TOOL_SPEC.output_schema,
        description=SENSITIVITY_TOOL_SPEC.description,
    )
    registry.register(spec)
