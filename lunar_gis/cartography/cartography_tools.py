"""M7 governed cartography tools: style_layer / create_layout / export_map.

- ``cartography.style_layer`` v1 (LOW): apply a deterministic StyleRule
  to a project layer.
- ``cartography.create_layout`` v1 (MEDIUM): build a print layout with
  map/title/legend/scalebar/north-arrow/provenance block.
- ``cartography.export_map`` v1 (MEDIUM): export a layout to a
  sandbox-scoped PDF/PNG.

Handlers resolve the live project via deferred import (fail-closed).
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
from lunar_gis.cartography.styles import validate_style_rule

TOOL_VERSION = ToolVersion(major=1, minor=0, patch=0)


def _spec(name: str, description: str, properties: dict[str, Any], required: list[str], risk: ToolRisk) -> ToolSpec:
    return ToolSpec(
        name=name,
        version=TOOL_VERSION,
        risk=risk,
        handler=None,
        input_schema={"type": "object", "properties": properties, "required": required, "additionalProperties": False},
        output_schema={"type": "object"},
        description=description,
    )


STYLE_LAYER_SPEC = _spec(
    "cartography.style_layer",
    "Apply a deterministic style rule to a project layer.",
    {
        "layer_id": {"type": "string"},
        "geometry": {"type": "string"},
        "method": {"type": "string"},
        "field": {"type": "string"},
        "classes": {"type": "integer"},
    },
    ["layer_id"],
    ToolRisk.LOW,
)

CREATE_LAYOUT_SPEC = _spec(
    "cartography.create_layout",
    "Build a print layout with legend, scalebar, north arrow, and provenance block.",
    {
        "title": {"type": "string"},
        "layer_ids": {"type": "array", "items": {"type": "string"}},
        "provenance_text": {"type": "string"},
        "layout_name": {"type": "string"},
    },
    ["title", "layer_ids"],
    ToolRisk.MEDIUM,
)

EXPORT_MAP_SPEC = _spec(
    "cartography.export_map",
    "Export a layout to sandbox-scoped PDF/PNG.",
    {
        "layout_name": {"type": "string"},
        "format": {"type": "string"},
        "output_relpath": {"type": "string"},
        "workspace_dir": {"type": "string"},
    },
    ["layout_name", "output_relpath"],
    ToolRisk.MEDIUM,
)


def _resolve_project() -> Any | None:
    try:
        from qgis.core import QgsProject  # type: ignore[import-not-found]

        return QgsProject.instance()
    except ImportError:
        return None


def _layer_id_or_none(layer: Any) -> str | None:
    try:
        ident = layer.id()
    except Exception:
        return None
    return str(ident) if isinstance(ident, str) else None


def _find_layer(project: Any, ref: str) -> Any | None:
    try:
        layers = project.mapLayers()
    except Exception:
        return None
    if ref in layers:
        return layers[ref]
    for layer in layers.values():
        if _layer_id_or_none(layer) == ref:
            return layer
    return None


def style_layer_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    from lunar_gis.cartography.layout_qgis import apply_style
    from lunar_gis.cartography.styles import ClassificationMethod, GeometryFamily, StyleRule

    project = _resolve_project()
    if project is None:
        return {"ok": False, "error": "qgis-runtime-unavailable"}
    layer = _find_layer(project, input_data.get("layer_id", ""))
    if layer is None:
        return {"ok": False, "error": "layer-not-found"}
    rule_data = {
        "geometry": input_data.get("geometry", "Point"),
        "method": input_data.get("method", "single-symbol"),
        "classes": input_data.get("classes", 5),
        "field": input_data.get("field"),
    }
    errors = validate_style_rule({k: v for k, v in rule_data.items() if v is not None})
    if errors:
        return {"ok": False, "error": f"invalid-rule: {'; '.join(errors)}"}
    try:
        rule = StyleRule(
            geometry=GeometryFamily(rule_data["geometry"]),
            method=ClassificationMethod(rule_data["method"]),
            classes=int(rule_data["classes"]),
            field=input_data.get("field"),
        )
    except ValueError as exc:
        return {"ok": False, "error": f"invalid-rule: {exc}"}
    try:
        return apply_style(layer, rule)
    except Exception as exc:
        return {"ok": False, "error": f"style-failed: {type(exc).__name__}"}


def create_layout_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    from lunar_gis.cartography.layout_qgis import create_layout

    project = _resolve_project()
    if project is None:
        return {"ok": False, "error": "qgis-runtime-unavailable"}
    try:
        return create_layout(
            project,
            str(input_data.get("title", "Map")),
            list(input_data.get("layer_ids", [])),
            provenance_text=str(input_data.get("provenance_text", "")),
            layout_name=str(input_data.get("layout_name", "Lunar GIS Map")),
        )
    except Exception as exc:
        return {"ok": False, "error": f"layout-failed: {type(exc).__name__}"}


def export_map_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    from lunar_gis.cartography.layout_qgis import export_layout

    project = _resolve_project()
    if project is None:
        return {"ok": False, "error": "qgis-runtime-unavailable"}
    fmt = input_data.get("format", "pdf")
    if fmt not in ("pdf", "png"):
        fmt = "pdf"
    relpath = input_data.get("output_relpath", "")
    normalized = str(relpath).replace("\\", "/").lstrip("/")
    if not normalized or normalized.startswith("~") or ":" in normalized or ".." in normalized.split("/"):
        return {"ok": False, "error": "path escapes sandbox"}
    if not normalized.endswith(f".{fmt}"):
        normalized += f".{fmt}"
    workspace = input_data.get("workspace_dir")
    if not isinstance(workspace, str) or not workspace or not os.path.isdir(workspace):
        return {"ok": False, "error": "workspace_dir required"}
    candidate = os.path.realpath(os.path.join(workspace, *normalized.split("/")))
    root = os.path.realpath(workspace)
    if candidate != root and not candidate.startswith(root + os.sep):
        return {"ok": False, "error": "path escapes sandbox"}
    try:
        manager = project.layoutManager()
        layout = None
        for existing in manager.printLayouts():
            if existing.name() == input_data.get("layout_name", "Lunar GIS Map"):
                layout = existing
                break
        if layout is None:
            return {"ok": False, "error": "layout-not-found"}
        return export_layout(layout, candidate, fmt)
    except Exception as exc:
        return {"ok": False, "error": f"export-failed: {type(exc).__name__}"}


def register_cartography_tools(registry: ToolRegistry) -> None:
    handlers = {
        "cartography.style_layer": style_layer_handler,
        "cartography.create_layout": create_layout_handler,
        "cartography.export_map": export_map_handler,
    }
    for spec in (STYLE_LAYER_SPEC, CREATE_LAYOUT_SPEC, EXPORT_MAP_SPEC):
        registry.register(
            ToolSpec(
                name=spec.name,
                version=spec.version,
                risk=spec.risk,
                handler=handlers[spec.name],
                input_schema=spec.input_schema,
                output_schema=spec.output_schema,
                description=spec.description,
            )
        )


__all__ = [
    "style_layer_handler",
    "create_layout_handler",
    "export_map_handler",
    "register_cartography_tools",
]
