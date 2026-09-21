"""M9 UI controller: offline-importable workspace orchestration.

Owns the ToolRegistry (all tool groups), the ControlledExecutor, and
the planning/context helpers the workspace tabs call. Qt widgets live
in ``workspace.py`` / ``dialogs.py`` — this module has deferred QGIS
imports only, so it is importable and testable without QGIS.

Every consequential action routes through ``run_tool`` (governed
execution). Confirmation artifacts are created from explicit user
confirmation in the dialog layer, never implicitly.
"""

from __future__ import annotations

from typing import Any

from lunar_gis.agent.execution import ConfirmationArtifact, ControlledExecutor
from lunar_gis.agent.registry import ToolExecutionContext, ToolRegistry

UI_CONTROLLER_VERSION = "1.0"


def build_registry() -> ToolRegistry:
    """Register every Lunar GIS tool group (single wiring point)."""
    from lunar_gis.analysis.gis_tools import register_gis_tools
    from lunar_gis.analysis.sensitivity_tools import register_sensitivity_tool
    from lunar_gis.analysis.tools import register_ahp_tool
    from lunar_gis.cartography.cartography_tools import register_cartography_tools
    from lunar_gis.data.data_tools import register_data_tools
    from lunar_gis.data.provider_tools import register_provider_tools
    from lunar_gis.data.transform_tools import register_transformation_tool
    from lunar_gis.reports.report_tools import register_report_tools

    registry = ToolRegistry()
    register_ahp_tool(registry)
    register_sensitivity_tool(registry)
    register_gis_tools(registry)
    register_transformation_tool(registry)
    register_provider_tools(registry)
    register_data_tools(registry)
    register_cartography_tools(registry)
    register_report_tools(registry)
    return registry


def create_executor(registry: ToolRegistry) -> ControlledExecutor:
    return ControlledExecutor(registry)


def default_context(session_id: str = "ui-session") -> ToolExecutionContext:
    return ToolExecutionContext(session_id=session_id)


def run_tool(
    executor: ControlledExecutor,
    tool_name: str,
    input_data: dict[str, Any],
    context: ToolExecutionContext,
    confirmation: ConfirmationArtifact | None = None,
) -> dict[str, Any]:
    """Execute one tool through governance. Never raises."""
    try:
        result = executor.execute(tool_name, input_data, context, confirmation)
    except Exception as exc:
        return {"ok": False, "tool_name": tool_name, "error": f"execution-failed: {type(exc).__name__}"}
    return {
        "ok": result.success,
        "tool_name": tool_name,
        "output": result.output.to_dict() if result.output is not None else None,
        "error": result.error,
    }


def confirmation_text(tool_name: str, input_data: dict[str, Any], registry: ToolRegistry) -> dict[str, Any]:
    """Human-readable confirmation content (what/data/source/output/risks)."""
    try:
        spec = registry.get(tool_name)
    except KeyError:
        return {"ok": False, "error": f"unknown tool: {tool_name}"}
    lines = [f"Tool: {spec.name} v{spec.version.to_str()} (risk: {spec.risk.value})", f"What: {spec.description}"]
    data = _summarize_input(tool_name, input_data)
    if data:
        lines.append(f"Data: {data}")
    if spec.risk.value == "high":
        lines.append(
            "Risks: consequential operation — downloads data, creates derived datasets, or runs expensive processing."
        )
    elif spec.risk.value == "medium":
        lines.append("Risks: network and/or file-system impact; results are verified before use.")
    else:
        lines.append("Risks: read-only or local low-impact operation.")
    lines.append("Provenance: this invocation is audit-recorded with input and context fingerprints.")
    return {"ok": True, "title": f"Confirm {spec.name}", "body": "\n".join(lines)}


def _summarize_input(tool_name: str, input_data: dict[str, Any]) -> str:
    bits: list[str] = []
    for key in ("layer_id", "dataset_id", "asset_id", "provider_id", "subject_ref", "title", "output_relpath"):
        value = input_data.get(key)
        if value:
            bits.append(f"{key}={value}")
    steps = input_data.get("steps")
    if isinstance(steps, list):
        bits.append(f"steps={len(steps)}:" + ",".join(str(s.get("op", "?")) for s in steps if isinstance(s, dict)))
    requirement = input_data.get("requirement")
    if isinstance(requirement, dict) and requirement.get("name"):
        bits.append(f"requirement={requirement.get('name')}")
    _ = tool_name
    return "; ".join(bits)


def ai_status() -> dict[str, Any]:
    """AI availability without touching secrets."""
    from lunar_gis.ai import openrouter as openrouter_module

    configured = openrouter_module.has_api_key()
    return {
        "configured": configured,
        "mode": "ai-assisted" if configured else "offline-deterministic",
        "offline_capable": True,
    }


def plan_request(user_request: str, registry: ToolRegistry) -> dict[str, Any]:
    """Plan a request (AI when configured, offline heuristic otherwise)."""
    from lunar_gis.ai.contracts import AIConfig
    from lunar_gis.ai.planner import plan_with_ai
    from lunar_gis.ai.toolcalling import registry_tool_schemas

    status = ai_status()
    if not status["configured"]:
        from lunar_gis.ai.planner import plan_offline

        result = plan_offline(user_request)
    else:
        result = plan_with_ai(user_request, [], AIConfig(), tool_schemas=registry_tool_schemas(registry))
    return {
        "ok": result.ok,
        "explanation": result.explanation,
        "requirement": result.requirement,
        "tool_calls": [
            {"tool_name": c.tool_name, "tool_version": c.tool_version, "arguments": c.arguments}
            for c in result.tool_calls
        ],
        "warnings": list(result.warnings),
        "error": result.error,
    }


def make_confirmation(
    tool_name: str, input_data: dict[str, Any], context: ToolExecutionContext, registry: ToolRegistry
) -> ConfirmationArtifact | None:
    """Build a scoped confirmation artifact (call only after explicit user consent)."""
    try:
        spec = registry.get(tool_name)
    except KeyError:
        return None
    return ConfirmationArtifact.create(tool_name, spec.version, input_data, context)


__all__ = [
    "UI_CONTROLLER_VERSION",
    "build_registry",
    "create_executor",
    "default_context",
    "run_tool",
    "confirmation_text",
    "ai_status",
    "plan_request",
    "make_confirmation",
]
