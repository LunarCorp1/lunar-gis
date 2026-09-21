"""M6 governed GIS analysis tools: buffer/intersection/dissolve/zonal/spatial-join.

Thin boundary between M1 tool contracts and pinned native algorithms.
Handlers resolve layers from the live project (deferred import,
fail-closed), execute via ``processing.run`` on the main thread, and
return memory output refs. GIS math stays in QGIS/Processing.

All tools are LOW risk (derived memory outputs, no project mutation,
no network). Destructive variants do not exist in v1.

Public API:
- GIS_TOOL_SPECS: tuple of ToolSpecs
- register_gis_tools(registry) -> None
"""

from __future__ import annotations

from typing import Any

from lunar_gis.agent.registry import (
    ToolRegistry,
    ToolRisk,
    ToolSpec,
    ToolVersion,
)

TOOL_VERSION = ToolVersion(major=1, minor=0, patch=0)

# Executor pins: op → (native Processing algorithm id, pinned version).
GIS_PINS: dict[str, tuple[str, str]] = {
    "buffer": ("native:buffer", "3.0"),
    "intersection": ("native:intersection", "3.0"),
    "dissolve": ("native:dissolve", "3.0"),
    "zonal_statistics": ("native:zonalstatisticsfb", "3.0"),
    "spatial_join": ("native:joinattributesbylocation", "3.0"),
}


def _spec(name: str, description: str, properties: dict[str, Any], required: list[str]) -> ToolSpec:
    return ToolSpec(
        name=name,
        version=TOOL_VERSION,
        risk=ToolRisk.LOW,
        handler=None,
        input_schema={"type": "object", "properties": properties, "required": required, "additionalProperties": False},
        output_schema={
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "output_ref": {"type": "string"},
                "evidence": {"type": "array", "items": {"type": "string"}},
                "error": {"type": "string"},
            },
            "required": ["ok"],
            "additionalProperties": False,
        },
        description=description,
    )


GIS_TOOL_SPECS: tuple[ToolSpec, ...] = (
    _spec(
        "analysis.buffer",
        "Fixed-distance buffer of a vector layer (native:buffer).",
        {"layer_id": {"type": "string"}, "distance": {"type": "number"}, "segments": {"type": "integer"}},
        ["layer_id", "distance"],
    ),
    _spec(
        "analysis.intersection",
        "Geometric intersection of two vector layers (native:intersection).",
        {"layer_id": {"type": "string"}, "overlay_layer_id": {"type": "string"}},
        ["layer_id", "overlay_layer_id"],
    ),
    _spec(
        "analysis.dissolve",
        "Dissolve features, optionally by field (native:dissolve).",
        {"layer_id": {"type": "string"}, "field": {"type": "string"}},
        ["layer_id"],
    ),
    _spec(
        "analysis.zonal_statistics",
        "Raster statistics per polygon zone (native:zonalstatisticsfb).",
        {"layer_id": {"type": "string"}, "raster_layer_id": {"type": "string"}},
        ["layer_id", "raster_layer_id"],
    ),
    _spec(
        "analysis.spatial_join",
        "Join attributes by spatial predicate (native:joinattributesbylocation).",
        {
            "layer_id": {"type": "string"},
            "join_layer_id": {"type": "string"},
            "predicate": {"type": "string"},
        },
        ["layer_id", "join_layer_id"],
    ),
)

_PREDICATES = ("intersects", "contains", "within", "touches", "overlaps")


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


def _run(op: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        import processing  # type: ignore[import-not-found]
    except ImportError:
        return {"ok": False, "error": "qgis-runtime-unavailable"}
    alg_id, _ = GIS_PINS[op]
    try:
        result = processing.run(alg_id, params)
        return {"ok": True, "output_ref": str(result.get("OUTPUT", "")), "evidence": [f"{op} via {alg_id}: ok"]}
    except Exception as exc:
        return {"ok": False, "error": f"{op} failed: {type(exc).__name__}"}


def buffer_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    project = _resolve_project()
    if project is None:
        return {"ok": False, "error": "qgis-runtime-unavailable"}
    layer = _find_layer(project, input_data.get("layer_id", ""))
    if layer is None:
        return {"ok": False, "error": "layer-not-found"}
    return _run(
        "buffer",
        {
            "INPUT": layer,
            "DISTANCE": float(input_data.get("distance", 0)),
            "SEGMENTS": int(input_data.get("segments", 5)),
            "DISSOLVE": False,
            "OUTPUT": "memory:",
        },
    )


def intersection_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    project = _resolve_project()
    if project is None:
        return {"ok": False, "error": "qgis-runtime-unavailable"}
    layer = _find_layer(project, input_data.get("layer_id", ""))
    overlay = _find_layer(project, input_data.get("overlay_layer_id", ""))
    if layer is None or overlay is None:
        return {"ok": False, "error": "layer-not-found"}
    return _run("intersection", {"INPUT": layer, "OVERLAY": overlay, "OUTPUT": "memory:"})


def dissolve_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    project = _resolve_project()
    if project is None:
        return {"ok": False, "error": "qgis-runtime-unavailable"}
    layer = _find_layer(project, input_data.get("layer_id", ""))
    if layer is None:
        return {"ok": False, "error": "layer-not-found"}
    fields = [input_data["field"]] if input_data.get("field") else []
    return _run("dissolve", {"INPUT": layer, "FIELD": fields, "OUTPUT": "memory:"})


def zonal_statistics_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    project = _resolve_project()
    if project is None:
        return {"ok": False, "error": "qgis-runtime-unavailable"}
    layer = _find_layer(project, input_data.get("layer_id", ""))
    raster = _find_layer(project, input_data.get("raster_layer_id", ""))
    if layer is None or raster is None:
        return {"ok": False, "error": "layer-not-found"}
    return _run(
        "zonal_statistics",
        {"INPUT": layer, "INPUT_RASTER": raster, "RASTER_BAND": 1, "STATISTICS": [0, 1, 2], "OUTPUT": "memory:"},
    )


def spatial_join_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    project = _resolve_project()
    if project is None:
        return {"ok": False, "error": "qgis-runtime-unavailable"}
    layer = _find_layer(project, input_data.get("layer_id", ""))
    join_layer = _find_layer(project, input_data.get("join_layer_id", ""))
    if layer is None or join_layer is None:
        return {"ok": False, "error": "layer-not-found"}
    predicate = input_data.get("predicate", "intersects")
    if predicate not in _PREDICATES:
        return {"ok": False, "error": f"unsupported predicate: {predicate}"}
    return _run(
        "spatial_join",
        {
            "INPUT": layer,
            "JOIN": join_layer,
            "PREDICATE": [_PREDICATES.index(predicate)],
            "JOIN_FIELDS": [],
            "METHOD": 0,
            "OUTPUT": "memory:",
        },
    )


_HANDLERS: dict[str, Any] = {
    "analysis.buffer": buffer_handler,
    "analysis.intersection": intersection_handler,
    "analysis.dissolve": dissolve_handler,
    "analysis.zonal_statistics": zonal_statistics_handler,
    "analysis.spatial_join": spatial_join_handler,
}


def register_gis_tools(registry: ToolRegistry) -> None:
    for spec in GIS_TOOL_SPECS:
        registry.register(
            ToolSpec(
                name=spec.name,
                version=spec.version,
                risk=spec.risk,
                handler=_HANDLERS[spec.name],
                input_schema=spec.input_schema,
                output_schema=spec.output_schema,
                description=spec.description,
            )
        )


__all__ = ["GIS_TOOL_SPECS", "register_gis_tools"]
