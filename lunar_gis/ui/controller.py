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
    from lunar_gis.analysis.suitability_tools import register_suitability_tool
    from lunar_gis.analysis.tools import register_ahp_tool
    from lunar_gis.cartography.cartography_tools import register_cartography_tools
    from lunar_gis.data.data_tools import register_data_tools
    from lunar_gis.data.provider_tools import register_provider_tools
    from lunar_gis.data.transform_tools import register_transformation_tool
    from lunar_gis.reports.report_tools import register_report_tools

    registry = ToolRegistry()
    register_ahp_tool(registry)
    register_sensitivity_tool(registry)
    register_suitability_tool(registry)
    register_gis_tools(registry)
    register_transformation_tool(registry)
    register_provider_tools(registry)
    register_data_tools(registry)
    register_cartography_tools(registry)
    register_report_tools(registry)
    return registry


def create_executor(registry: ToolRegistry) -> ControlledExecutor:
    return ControlledExecutor(registry)


def create_assistant_executor(registry: ToolRegistry) -> ControlledExecutor:
    """Executor for the Assistant loop: HIGH-only confirmation (M4 §12).

    Only ``data.download_dataset`` and ``data.run_transformation`` are
    confirmation-gated; search/validation/analysis run with intent audit
    but no dialog. Library defaults are untouched.
    """
    from lunar_gis.agent.governance import ConfirmationPolicy, PolicyEngine
    from lunar_gis.agent.registry import ToolRisk

    engine = PolicyEngine(confirmation_policy=ConfirmationPolicy(require_confirmation_risks=frozenset({ToolRisk.HIGH})))
    return ControlledExecutor(registry, engine)


def default_context(session_id: str = "ui-session") -> ToolExecutionContext:
    return ToolExecutionContext(session_id=session_id)


def run_tool(
    executor: ControlledExecutor,
    tool_name: str,
    input_data: dict[str, Any],
    context: ToolExecutionContext,
    confirmation: ConfirmationArtifact | None = None,
) -> dict[str, Any]:
    """Execute one tool through governance. Never raises.

    Two success levels (never conflated): ``ok`` = the governed
    execution succeeded (policy → confirmation → handler ran → output
    validated); ``handler_ok`` = the handler's own domain verdict
    (``output["ok"]`` when present, True when the handler returns no
    verdict field, False when the handler reports failure). A tool can
    execute perfectly and still report a domain failure (e.g. provider
    offline) — callers MUST branch on ``handler_ok`` for domain logic.
    """
    try:
        result = executor.execute(tool_name, input_data, context, confirmation)
    except Exception as exc:
        return {"ok": False, "tool_name": tool_name, "error": f"execution-failed: {type(exc).__name__}"}
    output_data = result.output.to_dict().get("data", {}) if result.output is not None else {}
    handler_ok = True
    handler_error = ""
    if isinstance(output_data, dict) and "ok" in output_data:
        handler_ok = bool(output_data["ok"])
        if not handler_ok:
            handler_error = str(output_data.get("error", "handler reported failure"))
    return {
        "ok": result.success,
        "tool_name": tool_name,
        "handler_ok": handler_ok and result.success,
        "handler_error": handler_error,
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


def history_segments(history: list[dict[str, str]] | None) -> list[Any]:
    """Prior turns → labeled segments (oldest first, last 6, budgeted)."""
    from lunar_gis.ai.context import MAX_TOTAL_CHARS
    from lunar_gis.ai.contracts import ContextSegment, TrustLabel

    segments: list[Any] = []
    total = 0
    for turn in (history or [])[-6:]:
        role = turn.get("role", "")
        text = turn.get("text", "")[:1500]
        if not text:
            continue
        label = TrustLabel.TRUSTED_USER if role == "user" else TrustLabel.ASSISTANT_HISTORY
        block = f"[{label.value}] prior {'request' if role == 'user' else 'answer'}: {text}"
        if total + len(block) > MAX_TOTAL_CHARS:
            break
        segments.append(ContextSegment(label=label, text=text))
        total += len(block)
    return segments


def plan_request(
    user_request: str,
    registry: ToolRegistry,
    history: list[dict[str, str]] | None = None,
    max_rounds: int = 3,
) -> dict[str, Any]:
    """Plan a request (AI when configured, offline heuristic otherwise).

    AI path runs a bounded agentic loop: model-proposed calls that need
    no confirmation execute through the assistant executor and their
    results feed the next round; HIGH-risk proposals are returned for
    explicit dialog confirmation, never auto-executed. Offline path is
    unchanged (single heuristic plan).
    """
    from lunar_gis.ai.context import engine_output_segment
    from lunar_gis.ai.contracts import AIConfig
    from lunar_gis.ai.planner import plan_with_ai
    from lunar_gis.ai.toolcalling import registry_tool_schemas, validate_call_against_registry

    status = ai_status()
    if not status["configured"]:
        from lunar_gis.ai.planner import plan_offline

        result = plan_offline(user_request)
        return {
            "ok": result.ok,
            "explanation": result.explanation,
            "requirement": result.requirement,
            "tool_calls": [
                {"tool_name": c.tool_name, "tool_version": c.tool_version, "arguments": c.arguments}
                for c in result.tool_calls
            ],
            "executed": [],
            "warnings": list(result.warnings),
            "error": result.error,
        }
    executor = create_assistant_executor(registry)
    context = default_context()
    segments = history_segments(history)
    executed: list[dict[str, Any]] = []
    seen: set[str] = set()
    all_pending: list[Any] = []
    final: Any = None
    for round_index in range(max(1, max_rounds)):
        if round_index > 0:
            segments.append(_summarize_instruction())
        result = plan_with_ai(user_request, segments, AIConfig(), tool_schemas=registry_tool_schemas(registry))
        if not result.ok:
            return {
                "ok": False,
                "explanation": "",
                "requirement": None,
                "tool_calls": [],
                "executed": executed,
                "warnings": [],
                "error": result.error,
            }
        final = result
        ran_any = False
        for call in result.tool_calls:
            call_dict = {
                "tool_name": call.tool_name,
                "tool_version": call.tool_version,
                "arguments": call.arguments,
            }
            valid, _ = validate_call_against_registry(call_dict, registry)
            fingerprint = call.tool_name + ":" + repr(sorted(call.arguments.items(), key=lambda kv: kv[0]))
            if not valid or fingerprint in seen:
                continue
            seen.add(fingerprint)
            outcome = run_tool(executor, call.tool_name, call.arguments, context)
            if not outcome["ok"] and "confirmation" in (outcome.get("error") or "").lower():
                if all(p.tool_name != call.tool_name for p in all_pending):
                    all_pending.append(call)
                continue
            ran_any = True
            summary = _summarize_output(call.tool_name, outcome)
            output_data = (outcome.get("output") or {}).get("data", {}) if outcome.get("ok") else {}
            # Domain verdict (handler_ok), never just execution success: a
            # perfectly executed call can still report domain failure.
            entry_ok = bool(outcome["ok"] and outcome.get("handler_ok", True))
            executed.append({"tool_name": call.tool_name, "ok": entry_ok, "summary": summary, "output": output_data})
            segments.append(engine_output_segment(call.tool_name, {"ok": entry_ok, "summary": summary}))
        if not ran_any:
            break
    if final is None:  # max_rounds < 1 guard (loop always runs at least once)
        return {
            "ok": False,
            "explanation": "",
            "requirement": None,
            "tool_calls": [],
            "executed": executed,
            "warnings": [],
            "error": "planner produced no result",
        }
    explanation = _strip_machine_blocks(final.explanation)
    if not explanation.strip() and executed:
        # The model said nothing (or only machine-channel blocks):
        # narrate what was actually found from evidence.
        explanation = _narrate_executed(executed)
    if not explanation.strip():
        explanation = final.explanation
    return {
        "ok": final.ok,
        "explanation": explanation,
        "requirement": final.requirement,
        "tool_calls": [
            {"tool_name": c.tool_name, "tool_version": c.tool_version, "arguments": c.arguments} for c in all_pending
        ],
        "executed": executed,
        "warnings": list(final.warnings),
        "error": final.error,
    }


def _summarize_instruction() -> Any:
    """Trusted follow-up nudge: answer from evidence, act when obvious."""
    from lunar_gis.ai.contracts import ContextSegment, TrustLabel

    return ContextSegment(
        label=TrustLabel.TRUSTED_SYSTEM,
        text=(
            "Summarize the engine results above in 2-4 concrete sentences "
            "(real layers, verdicts, counts). If one more tool call is the "
            "clear next step, make it; otherwise answer with explanation only."
        ),
    )


def _strip_machine_blocks(explanation: str) -> str:
    """Remove machine-channel fenced blocks from model text.

    Executed calls render separately from the ``executed`` record, so
    inline JSON would only confuse. May return "" (the caller narrates
    from evidence or falls back to the original).
    """
    import re

    stripped = re.sub(r"```json\s*\{.*?\}\s*```", "", explanation or "", flags=re.DOTALL)
    return "\n".join(line for line in stripped.splitlines() if line.strip()).strip()


def clean_display(text: str) -> str:
    """Unescape (twice) then escape for transcript display.

    Models echo escaped entities seen in context ("&quot;", sometimes
    doubly as "&amp;quot;"); resolving twice normalizes both to
    characters, and the final escape keeps real markup inert.
    Idempotent-safe against XSS either way.
    """
    import html

    once = html.unescape(text or "")
    return html.escape(html.unescape(once))


def _narrate_executed(executed: list[dict[str, Any]]) -> str:
    """Deterministic evidence-grounded narration (no model needed)."""
    import json

    parts: list[str] = []
    for entry in executed:
        name = entry.get("tool_name", "?")
        if not entry.get("ok"):
            reason = str(entry.get("summary", "")).replace("failed:", "").strip()[:200]
            parts.append(f"{name} failed ({reason})." if reason else f"{name} failed.")
            continue
        payload = entry.get("output") or {}
        if not isinstance(payload, dict) or not payload:
            # Legacy shape: re-parse the truncated summary (may be "?").
            summary = entry.get("summary", "")
            try:
                payload = json.loads(summary.split(":", 1)[1]) if ":" in summary else {}
            except (ValueError, IndexError):
                payload = {}
        if name == "data.describe_project" and isinstance(payload, dict):
            records = payload.get("records", [])
            if not records:
                parts.append("The project currently has no layers loaded.")
            else:
                shown = ", ".join(
                    f"{r.get('name')} [{r.get('geometry_type')}, {r.get('feature_count')} features]"
                    for r in records[:10]
                    if isinstance(r, dict)
                )
                extra = f" (+{len(records) - 10} more)" if len(records) > 10 else ""
                parts.append(f"Project layers ({len(records)}): {shown}{extra}.")
        elif name == "data.check_requirement" and isinstance(payload, dict):
            parts.append(
                f"Requirement check: {payload.get('availability', '?')} "
                f"({payload.get('fulfillment_kind', '?')}"
                f"{', ' + str(payload.get('missing_reason')) if payload.get('missing_reason') else ''})."
            )
        elif name == "data.search_catalog" and isinstance(payload, dict):
            results = payload.get("results", [])
            titles = "; ".join(str(r.get("title", "?"))[:80] for r in results[:5] if isinstance(r, dict))
            parts.append(f"Catalog search: {payload.get('total', len(results))} result(s). {titles}".rstrip(". ") + ".")
        elif name == "data.validate_dataset" and isinstance(payload, dict):
            parts.append(f"Validation verdict: {payload.get('verdict', '?')}.")
        elif name == "data.download_dataset" and isinstance(payload, dict):
            parts.append(
                f"Downloaded {payload.get('size_bytes', '?')} bytes "
                f"(sha {str(payload.get('sha256', ''))[:12]}) to {payload.get('sandbox_relpath', '?')}."
            )
        elif name == "data.load_into_project" and isinstance(payload, dict):
            parts.append(f"Loaded layer '{payload.get('layer_name', '?')}' into the project.")
        else:
            parts.append(f"{name} completed.")
    parts.append("See the Results tab for details.")
    return " ".join(parts)


def _summarize_output(tool_name: str, outcome: dict[str, Any]) -> str:
    """Privacy-safe one-line summary of an executed call (truncated).

    Reports domain failure (handler error) distinctly from execution
    failure so the model and narration never mistake one for success.
    """
    import json

    if not outcome.get("ok"):
        return f"failed: {(outcome.get('error') or '')[:200]}"
    if not outcome.get("handler_ok", True):
        return f"failed: {(outcome.get('handler_error') or 'handler reported failure')[:200]}"
    output = (outcome.get("output") or {}).get("data", {})
    try:
        text = json.dumps(output, default=str)
    except (TypeError, ValueError):
        text = str(output)
    return f"{tool_name}: {text[:800]}"


_AFFIRMATIONS = frozenset(
    {
        "yes",
        "y",
        "yes please",
        "proceed",
        "confirm",
        "confirmed",
        "do it",
        "go ahead",
        "ok",
        "okay",
        "download it",
        "run it",
        "run them",
        "yes download",
        "yes do it",
    }
)


def is_affirmation(text: str) -> bool:
    """Conservative yes-detection for confirming pending HIGH-risk proposals.

    Exact match on a small set, or a leading yes/proceed/confirm word.
    Anything else routes to normal planning (never auto-confirms).
    """
    import re
    import string

    normalized = (text or "").strip().lower()
    normalized = normalized.translate(str.maketrans("", "", string.punctuation)).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    if normalized in _AFFIRMATIONS:
        return True
    return normalized.startswith(("yes ", "proceed ", "confirm "))


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
    "create_assistant_executor",
    "default_context",
    "run_tool",
    "confirmation_text",
    "ai_status",
    "history_segments",
    "is_affirmation",
    "clean_display",
    "plan_request",
    "make_confirmation",
]
