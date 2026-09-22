"""M6 governed suitability tool: analysis.suitability v1 (LOW).

Thin boundary between M1 tool contracts and the suitability engine.
Handler resolves the live layer (deferred import, fail-closed), reads
numeric criterion fields on the main thread, runs the pure WLC engine,
and writes a memory output layer with score + class fields. GIS/math
authority split preserved: engine computes, QGIS iterates/stores.

Public API:
- SUITABILITY_TOOL_SPEC, suitability_handler, register_suitability_tool
"""

from __future__ import annotations

from typing import Any

from lunar_gis.agent.registry import (
    ToolRegistry,
    ToolRisk,
    ToolSpec,
    ToolVersion,
)
from lunar_gis.analysis.suitability import Direction, SuitabilityCriterion

SUITABILITY_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "layer_id": {"type": "string"},
        "criteria": {
            "type": "array",
            "items": {"type": "object"},
        },
        "score_field": {"type": "string"},
    },
    "required": ["layer_id", "criteria"],
    "additionalProperties": False,
}

SUITABILITY_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "output_ref": {"type": "string"},
        "scored_count": {"type": "integer"},
        "excluded_nulls": {"type": "integer"},
        "statistics": {"type": "object"},
        "method": {"type": "string"},
        "input_hash": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "error": {"type": "string"},
    },
    "required": ["ok"],
    "additionalProperties": False,
}

SUITABILITY_TOOL_SPEC = ToolSpec(
    name="analysis.suitability",
    version=ToolVersion(major=1, minor=0, patch=0),
    risk=ToolRisk.LOW,
    handler=None,
    input_schema=SUITABILITY_INPUT_SCHEMA,
    output_schema=SUITABILITY_OUTPUT_SCHEMA,
    description=(
        "Weighted-linear-combination suitability scoring over a vector layer "
        "(min-max normalization, weights sum to 1). Returns a scored memory layer."
    ),
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


def _feature_id_or_none(feature: Any) -> Any:
    try:
        return feature.id()
    except Exception:
        return None


def _best_effort(call: Any, *args: Any) -> bool:
    try:
        call(*args)
        return True
    except Exception:
        return False


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


def parse_criteria(raw: list[Any]) -> tuple[SuitabilityCriterion, ...]:
    """Parse criterion mappings (raises ValueError)."""
    criteria: list[SuitabilityCriterion] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("criteria entries must be objects")
        field = item.get("field", "")
        weight = item.get("weight", 0)
        direction = item.get("direction", "benefit")
        if not isinstance(field, str) or not field:
            raise ValueError("criterion.field must be a non-empty string")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool):
            raise ValueError(f"criterion weight for {field!r} must be a number")
        try:
            direction_enum = Direction(direction)
        except ValueError:
            raise ValueError(f"criterion direction for {field!r} must be benefit|cost") from None
        criteria.append(SuitabilityCriterion(field=field, weight=float(weight), direction=direction_enum))
    return tuple(criteria)


def score_layer(layer: Any, criteria: tuple[SuitabilityCriterion, ...], score_field: str) -> dict[str, Any]:
    """Score a live vector layer object. Returns a JSON-compatible result dict."""
    from lunar_gis.analysis.suitability import suitability_wlc

    try:
        from qgis.core import QgsFeature, QgsField, QgsVectorLayer  # type: ignore[import-not-found]
        from qgis.PyQt.QtCore import QVariant  # type: ignore[import-not-found]
    except ImportError:
        return {"ok": False, "error": "qgis-runtime-unavailable"}
    try:
        units: list[dict[str, Any]] = []
        keys: list[Any] = []
        for feature in layer.getFeatures():
            row = {}
            for criterion in criteria:
                try:
                    row[criterion.field] = feature.attribute(criterion.field)
                except Exception:
                    row[criterion.field] = None
            units.append(row)
            try:
                keys.append(feature.id())
            except Exception:
                keys.append(len(keys))
        result = suitability_wlc(units, list(criteria), keys=keys)
    except ValueError as exc:
        return {"ok": False, "error": f"suitability-failed: {exc}"}
    except Exception:
        return {"ok": False, "error": "suitability-failed: iteration error"}
    try:
        try:
            crs_authid = layer.crs().authid()
        except Exception:
            crs_authid = "EPSG:4326"
        try:
            geom = layer.geometryType()
        except Exception:
            geom = 0
        if geom == 0:
            uri = f"Point?crs={crs_authid}"
        elif geom == 1:
            uri = f"LineString?crs={crs_authid}"
        else:
            uri = f"Polygon?crs={crs_authid}"
        try:
            layer_name = layer.name()
        except Exception:
            layer_name = "suitability"
        out = QgsVectorLayer(uri, f"{layer_name}_suitability", "memory")
        provider = out.dataProvider()
        try:
            fields = list(layer.fields().toList())
        except Exception:
            fields = []
        provider.addAttributes(fields)
        provider.addAttributes(
            [QgsField(score_field, QVariant.Double), QgsField(f"{score_field}_class", QVariant.String)]
        )
        out.updateFields()
        by_key = {unit.key: unit for unit in result.scores}
        created = 0
        out.startEditing()
        try:
            for feature in layer.getFeatures():
                fid = _feature_id_or_none(feature)
                if fid is None:
                    continue
                scored = by_key.get(fid)
                if scored is None:
                    continue
                values = feature.attributes() + [scored.score, scored.suitability_class]
                new_feature = QgsFeature(out.fields())
                new_feature.setAttributes(values)
                try:
                    geometry = feature.geometry()
                except Exception:
                    geometry = None
                if geometry is not None:
                    _best_effort(new_feature.setGeometry, geometry)
                if out.addFeature(new_feature):
                    created += 1
        finally:
            _best_effort(out.commitChanges)
    except Exception:
        return {"ok": False, "error": "suitability-failed: output build error"}
    return {
        "ok": True,
        "output_ref": f"memory:{layer_name}_suitability",
        "scored_count": created,
        "excluded_nulls": result.excluded_nulls,
        "statistics": result.statistics,
        "method": result.method,
        "input_hash": result.input_hash,
        "evidence": [f"suitability wlc: {created} scored, {result.excluded_nulls} excluded"],
    }


def suitability_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    """Score a project vector layer by id. Never raises."""
    project = _resolve_project()
    if project is None:
        return {"ok": False, "error": "qgis-runtime-unavailable"}
    layer = _find_layer(project, input_data.get("layer_id", ""))
    if layer is None:
        return {"ok": False, "error": "layer-not-found"}
    if not hasattr(layer, "getFeatures"):
        return {"ok": False, "error": "suitability requires a vector layer"}
    try:
        criteria = parse_criteria(input_data.get("criteria", []))
    except ValueError as exc:
        return {"ok": False, "error": f"invalid-criteria: {exc}"}
    score_field = input_data.get("score_field", "suitability") or "suitability"
    return score_layer(layer, criteria, score_field)


def register_suitability_tool(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name=SUITABILITY_TOOL_SPEC.name,
            version=SUITABILITY_TOOL_SPEC.version,
            risk=SUITABILITY_TOOL_SPEC.risk,
            handler=suitability_handler,
            input_schema=SUITABILITY_INPUT_SCHEMA,
            output_schema=SUITABILITY_OUTPUT_SCHEMA,
            description=SUITABILITY_TOOL_SPEC.description,
        )
    )


__all__ = ["SUITABILITY_TOOL_SPEC", "suitability_handler", "register_suitability_tool", "parse_criteria", "score_layer"]
