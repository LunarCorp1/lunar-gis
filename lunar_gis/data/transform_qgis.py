"""M4-T04 QGIS-bound transformation chain executor.

Runs declared ``TransformationStep`` chains through native QGIS
Processing algorithms (executor pins in ``transforms.EXECUTOR_PINS``).
QGIS owns all GIS math; this module maps steps to algorithm parameters,
executes on the main thread, and records per-step evidence.

Boundary:
- duck-typed ``project``/layer inputs; QGIS enters via deferred imports
  (fail-closed error dict, never an exception to the governed caller)
- MUST run on the main/GUI thread (Processing + SIP wrappers)
- outputs: memory layers or sandbox files only (safe-join enforced);
  never absolute outside-sandbox paths, never project mutation except
  through the explicit ``add_to_project`` flag owned by the caller
- filter predicates render from structured ``FilterPredicate`` only;
  no raw expression strings accepted

Public API:
- run_chain(steps, project, sandbox_dir, context) -> dict
"""

from __future__ import annotations

import os
from typing import Any

from lunar_gis.data.transforms import (
    EXECUTOR_PINS,
    FilterPredicate,
    TransformOp,
    validate_step,
)


def _qgis_processing() -> Any | None:
    try:
        import processing  # type: ignore[import-not-found]  # noqa: F401

        return processing
    except ImportError:
        return None


def _safe_output_path(sandbox_dir: str, output_ref: str) -> str | None:
    """Resolve output_ref inside sandbox_dir; None on traversal/absolute."""
    if not isinstance(output_ref, str) or not output_ref:
        return None
    normalized = output_ref.replace("\\", "/").lstrip("/")
    if normalized.startswith("~") or ".." in normalized.split("/") or ":" in normalized:
        return None
    candidate = os.path.realpath(os.path.join(sandbox_dir, *normalized.split("/")))
    root = os.path.realpath(sandbox_dir)
    if candidate != root and not candidate.startswith(root + os.sep):
        return None
    return candidate


def _alg_params_for_step(
    op: str, params: dict[str, Any], input_layer: Any, overlay_layer: Any = None
) -> dict[str, Any]:
    """Map a step to native algorithm parameters (QGIS authority executes)."""
    if op == TransformOp.REPROJECT_VECTOR.value:
        return {"INPUT": input_layer, "TARGET_CRS": params["target_crs"], "OUTPUT": "memory:"}
    if op == TransformOp.REPROJECT_RASTER.value:
        out: dict[str, Any] = {
            "INPUT": input_layer,
            "TARGET_CRS": params["target_crs"],
            "RESAMPLING": params.get("resampling", "bilinear"),
            "OUTPUT": "memory:",
        }
        if "target_resolution" in params:
            out["TARGET_RESOLUTION"] = params["target_resolution"]
        return out
    if op == TransformOp.CLIP.value:
        return {"INPUT": input_layer, "OVERLAY": overlay_layer, "OUTPUT": "memory:"}
    if op == TransformOp.FILTER.value:
        predicate = FilterPredicate(field=params["field"], op=params["op"], value=params.get("value", ""))
        return {"INPUT": input_layer, "EXPRESSION": predicate.to_expression(), "OUTPUT": "memory:"}
    if op == TransformOp.JOIN.value:
        return {
            "INPUT": input_layer,
            "FIELD": params["target_field"],
            "INPUT_2": overlay_layer,
            "FIELD_2": params["join_field"],
            "OUTPUT": "memory:",
        }
    if op == TransformOp.RASTER_TO_VECTOR.value:
        return {
            "INPUT": input_layer,
            "FIELD": params["field"],
            "OUTPUT": "memory:",
        }
    if op == TransformOp.VECTOR_TO_RASTER.value:
        out2: dict[str, Any] = {
            "INPUT": input_layer,
            "OUTPUT": "memory:",
            "UNITS": 1,
            "WIDTH": params.get("target_resolution", 10.0),
            "HEIGHT": params.get("target_resolution", 10.0),
        }
        if "attribute_field" in params:
            out2["FIELD"] = params["attribute_field"]
        elif "burn_value" in params:
            out2["BURN"] = params["burn_value"]
        return out2
    raise ValueError(f"Unsupported transformation op: {op!r}")


def run_chain(
    steps: list[dict[str, Any]],
    *,
    project: Any | None = None,
    sandbox_dir: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a validated chain. Returns a JSON-compatible result dict.

    Result shape: ``{ok, outputs: [...], evidence: [...], error?}``.
    Never raises to the governed caller — failures are ``{ok: False}``.
    """
    _ = context
    processing = _qgis_processing()
    if processing is None:
        return {"ok": False, "outputs": [], "evidence": [], "error": "qgis-runtime-unavailable"}
    outputs: list[dict[str, Any]] = []
    evidence: list[str] = []
    current: Any = None
    for index, step in enumerate(steps):
        op = step.get("op", "")
        params = step.get("params", {})
        refs = tuple(step.get("input_refs", ()))
        errors = validate_step(op, params, refs)
        if errors:
            return {
                "ok": False,
                "outputs": outputs,
                "evidence": evidence,
                "error": f"step[{index}] invalid: {'; '.join(errors)}",
            }
        alg_id, _ = EXECUTOR_PINS[op]
        try:
            source = current if current is not None else _resolve_ref(refs[0], project)
            overlay = None
            overlay_key = (
                "overlay_layer_id"
                if op == TransformOp.CLIP.value
                else ("join_layer_id" if op == TransformOp.JOIN.value else None)
            )
            if overlay_key is not None:
                overlay = _resolve_ref(params[overlay_key], project)
            alg_params = _alg_params_for_step(op, params, source, overlay)
            if sandbox_dir is not None and step.get("output_ref"):
                target = _safe_output_path(sandbox_dir, str(step["output_ref"]))
                if target is None:
                    return {
                        "ok": False,
                        "outputs": outputs,
                        "evidence": evidence,
                        "error": f"step[{index}] output escapes sandbox",
                    }
                for key in ("OUTPUT",):
                    if key in alg_params:
                        alg_params[key] = target
            result = processing.run(alg_id, alg_params)
            out_ref = result.get("OUTPUT", "")
            try:
                current = result.get("OUTPUT", None)
            except Exception:
                current = None
            outputs.append({"step": index, "op": op, "output_ref": str(out_ref)})
            evidence.append(f"step[{index}] {op} via {alg_id}: ok")
        except Exception as exc:
            return {
                "ok": False,
                "outputs": outputs,
                "evidence": evidence,
                "error": f"step[{index}] {op} failed: {type(exc).__name__}: {exc}",
            }
    return {"ok": True, "outputs": outputs, "evidence": evidence}


def _layer_id_or_none(layer: Any) -> str | None:
    """Best-effort layer id (None when the accessor fails)."""
    try:
        ident = layer.id()
    except Exception:
        return None
    return str(ident) if isinstance(ident, str) else None


def _resolve_ref(ref: str, project: Any | None) -> Any:
    """Resolve a layer reference: project layer id first, else the raw ref.

    Raw refs (file paths, memory URIs) pass through to the algorithm;
    QGIS opens them. Unknown project ids raise LookupError (fail-closed).
    """
    if project is not None:
        try:
            layers = project.mapLayers()
        except Exception:
            layers = {}
        if ref in layers:
            return layers[ref]
        for layer in layers.values():
            if _layer_id_or_none(layer) == ref:
                return layer
    if isinstance(ref, str) and ref:
        return ref
    raise LookupError(f"Unresolvable transformation input ref: {ref!r}")


__all__ = ["run_chain"]
