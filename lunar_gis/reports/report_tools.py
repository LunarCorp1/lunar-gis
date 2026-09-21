"""M8 governed report tools: reports.generate / reports.export.

- ``reports.generate`` v1 (LOW): build a ReportModel from structured
  sections and render accessible HTML (in-memory; no file I/O).
- ``reports.export`` v1 (MEDIUM): write rendered HTML to a
  sandbox-scoped ``.html`` path.

Handlers are QGIS-free and offline-capable. Filenames are
sandbox-scoped; content strings are escaped at render time.
"""

from __future__ import annotations

import os
from typing import Any

from lunar_gis.agent.registry import (
    ToolRegistry,
    ToolRisk,
    ToolSpec,
    ToolVersion,
)

TOOL_VERSION = ToolVersion(major=1, minor=0, patch=0)

GENERATE_SPEC = ToolSpec(
    name="reports.generate",
    version=TOOL_VERSION,
    risk=ToolRisk.LOW,
    handler=None,
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "user_request": {"type": "string"},
            "sections": {"type": "object"},
        },
        "required": ["title", "user_request"],
        "additionalProperties": False,
    },
    output_schema={"type": "object"},
    description="Build a reproducible report model and render accessible HTML.",
)

EXPORT_SPEC = ToolSpec(
    name="reports.export",
    version=TOOL_VERSION,
    risk=ToolRisk.MEDIUM,
    handler=None,
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "user_request": {"type": "string"},
            "sections": {"type": "object"},
            "output_relpath": {"type": "string"},
            "workspace_dir": {"type": "string"},
        },
        "required": ["title", "user_request", "output_relpath", "workspace_dir"],
        "additionalProperties": False,
    },
    output_schema={"type": "object"},
    description="Render a report and write it to a sandbox-scoped HTML file.",
)


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _build_report(title: str, user_request: str, sections: dict[str, Any]) -> dict[str, Any]:
    from lunar_gis.reports.html import render_html
    from lunar_gis.reports.models import ReportContent, ReportEnvelope, ReportModel, content_identity, make_content

    content: ReportContent = make_content(
        title,
        user_request,
        requirements=tuple(sections.get("requirements", ())),
        data_used=tuple(sections.get("data_used", ())),
        missing_data=tuple(sections.get("missing_data", ())),
        transformations=tuple(sections.get("transformations", ())),
        analysis=tuple(sections.get("analysis", ())),
        results=tuple(sections.get("results", ())),
        assumptions=tuple(sections.get("assumptions", ())),
        warnings=tuple(sections.get("warnings", ())),
        provenance=tuple(sections.get("provenance", ())),
        licenses=tuple(sections.get("licenses", ())),
        engine_versions=dict(sections.get("engine_versions", {})),
        policy_versions=dict(sections.get("policy_versions", {})),
    )
    envelope = ReportEnvelope(generated_at=_utc_now())
    model = ReportModel(content=content, envelope=envelope)
    return {"model": model, "html": render_html(model), "identity": content_identity(content)}


def generate_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    try:
        sections = input_data.get("sections", {})
        built = _build_report(
            str(input_data["title"]), str(input_data["user_request"]), sections if isinstance(sections, dict) else {}
        )
    except (KeyError, ValueError) as exc:
        return {"ok": False, "error": f"invalid-report: {exc}"}
    except Exception as exc:
        return {"ok": False, "error": f"render-failed: {type(exc).__name__}"}
    return {"ok": True, "identity": built["identity"], "html_chars": len(built["html"]), "html": built["html"]}


def export_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    relpath = str(input_data.get("output_relpath", "")).replace("\\", "/").lstrip("/")
    if not relpath or relpath.startswith("~") or ":" in relpath or ".." in relpath.split("/"):
        return {"ok": False, "error": "path escapes sandbox"}
    if not relpath.endswith(".html"):
        relpath += ".html"
    workspace = input_data.get("workspace_dir", "")
    if not isinstance(workspace, str) or not workspace or not os.path.isdir(workspace):
        return {"ok": False, "error": "workspace_dir required"}
    candidate = os.path.realpath(os.path.join(workspace, *relpath.split("/")))
    root = os.path.realpath(workspace)
    if candidate != root and not candidate.startswith(root + os.sep):
        return {"ok": False, "error": "path escapes sandbox"}
    result = generate_handler(input_data)
    if not result.get("ok"):
        return result
    try:
        parent = os.path.dirname(candidate)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(candidate, "w", encoding="utf-8") as handle:
            handle.write(result["html"])
    except OSError as exc:
        return {"ok": False, "error": f"write-failed: {exc}"}
    return {"ok": True, "identity": result["identity"], "path": candidate, "sandbox_relpath": relpath}


def register_report_tools(registry: ToolRegistry) -> None:
    for spec, handler in ((GENERATE_SPEC, generate_handler), (EXPORT_SPEC, export_handler)):
        registry.register(
            ToolSpec(
                name=spec.name,
                version=spec.version,
                risk=spec.risk,
                handler=handler,
                input_schema=spec.input_schema,
                output_schema=spec.output_schema,
                description=spec.description,
            )
        )


__all__ = ["generate_handler", "export_handler", "register_report_tools"]
