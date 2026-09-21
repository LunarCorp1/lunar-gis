"""M4-T04 transformation contracts (QGIS-free).

Declares — never computes — the frozen §8 transformation boundary:

- closed 7-op set with preserving/transforming split
- per-op parameter schemas (registry-validator compatible)
- TransformationStep / TransformationChain frozen records
- chain validation (length caps, op allowlist, output_ref policy)

Executor bindings (native Processing algorithm id + version pins) live
here as data; execution lives in ``transform_qgis`` (QGIS-bound) and is
invoked only through the governed ``data.run_transformation`` tool.

No ``qgis.*``, no ``project``, no network imports. Import-guard tested.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

TRANSFORM_MODEL_VERSION = "1.0"

# Implementation config (non-normative) per M4 §16.
MAX_CHAIN_STEPS = 3


class TransformOp(str, Enum):
    """Closed §8 op set. No merge op in v1 (frozen merge-exclusion)."""

    REPROJECT_VECTOR = "reproject-vector"
    REPROJECT_RASTER = "reproject-raster"
    CLIP = "clip"
    FILTER = "filter"
    JOIN = "join"
    RASTER_TO_VECTOR = "raster-to-vector"
    VECTOR_TO_RASTER = "vector-to-raster"


# Information behavior split (§8): preserving ops keep the information
# content modulo numeric precision; transforming ops require method
# params + warnings + mandatory DERIVED provenance.
PRESERVING_OPS: frozenset[str] = frozenset(
    {
        TransformOp.REPROJECT_VECTOR.value,
        TransformOp.CLIP.value,
        TransformOp.FILTER.value,
    }
)

TRANSFORMING_OPS: frozenset[str] = frozenset(
    {
        TransformOp.JOIN.value,
        TransformOp.RASTER_TO_VECTOR.value,
        TransformOp.VECTOR_TO_RASTER.value,
        TransformOp.REPROJECT_RASTER.value,
    }
)

# Executor pins: op → (native Processing algorithm id, pinned version).
# Versions are QGIS-version-qualified strings of the algorithm contract
# as shipped; re-pinned only by explicit review.
EXECUTOR_PINS: dict[str, tuple[str, str]] = {
    TransformOp.REPROJECT_VECTOR.value: ("native:reprojectlayer", "3.0"),
    TransformOp.REPROJECT_RASTER.value: ("gdal:warpreproject", "3.0"),
    TransformOp.CLIP.value: ("native:clip", "3.0"),
    TransformOp.FILTER.value: ("native:extractbyexpression", "3.0"),
    TransformOp.JOIN.value: ("native:joinattributestable", "3.0"),
    TransformOp.RASTER_TO_VECTOR.value: ("gdal:polygonize", "3.0"),
    TransformOp.VECTOR_TO_RASTER.value: ("gdal:rasterize", "3.0"),
}

# Filter predicate operators (§8: structured predicate, never a raw
# QGIS expression string from untrusted input).
FILTER_OPERATORS: frozenset[str] = frozenset({"=", "!=", "<", "<=", ">", ">=", "IS NULL", "IS NOT NULL", "IN", "LIKE"})


def _param_schemas() -> dict[str, dict[str, Any]]:
    """Per-op parameter schemas (registry-validator compatible)."""
    crs_prop = {"type": "string"}
    return {
        TransformOp.REPROJECT_VECTOR.value: {
            "type": "object",
            "properties": {"target_crs": crs_prop},
            "required": ["target_crs"],
            "additionalProperties": False,
        },
        TransformOp.REPROJECT_RASTER.value: {
            "type": "object",
            "properties": {
                "target_crs": crs_prop,
                "resampling": {"type": "string"},
                "target_resolution": {"type": "number"},
                "nodata": {"type": "number"},
            },
            "required": ["target_crs", "resampling"],
            "additionalProperties": False,
        },
        TransformOp.CLIP.value: {
            "type": "object",
            "properties": {"overlay_layer_id": {"type": "string"}},
            "required": ["overlay_layer_id"],
            "additionalProperties": False,
        },
        TransformOp.FILTER.value: {
            "type": "object",
            "properties": {
                "field": {"type": "string"},
                "op": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["field", "op"],
            "additionalProperties": False,
        },
        TransformOp.JOIN.value: {
            "type": "object",
            "properties": {
                "join_layer_id": {"type": "string"},
                "join_field": {"type": "string"},
                "target_field": {"type": "string"},
                "join_type": {"type": "string"},
            },
            "required": ["join_layer_id", "join_field", "target_field"],
            "additionalProperties": False,
        },
        TransformOp.RASTER_TO_VECTOR.value: {
            "type": "object",
            "properties": {
                "field": {"type": "string"},
                "threshold": {"type": "number"},
                "nodata": {"type": "number"},
            },
            "required": ["field"],
            "additionalProperties": False,
        },
        TransformOp.VECTOR_TO_RASTER.value: {
            "type": "object",
            "properties": {
                "attribute_field": {"type": "string"},
                "target_resolution": {"type": "number"},
                "burn_value": {"type": "number"},
                "nodata": {"type": "number"},
            },
            "required": ["target_resolution"],
            "additionalProperties": False,
        },
    }


PARAM_SCHEMAS: dict[str, dict[str, Any]] = _param_schemas()


@dataclass(frozen=True)
class FilterPredicate:
    """Structured attribute predicate (§8). Never a raw expression."""

    field: str
    op: str
    value: str = ""

    def to_expression(self) -> str:
        """Render a deterministic QGIS expression from the predicate.

        Field names are double-quoted with embedded quotes doubled;
        string values are single-quoted with embedded quotes doubled.
        Numeric-looking values pass through unquoted.
        """
        if self.op not in FILTER_OPERATORS:
            raise ValueError(f"Unsupported filter operator: {self.op!r}")
        quoted = '"' + self.field.replace('"', '""') + '"'
        if self.op in ("IS NULL", "IS NOT NULL"):
            return f"{quoted} {self.op}"
        if self.op == "IN":
            items = [item.strip() for item in self.value.split(",") if item.strip()]
            rendered = ", ".join(_render_literal(item) for item in items)
            return f"{quoted} IN ({rendered})"
        if self.op == "LIKE":
            return f"{quoted} LIKE {_render_literal(self.value)}"
        return f"{quoted} {self.op} {_render_literal(self.value)}"


def _render_literal(raw: str) -> str:
    try:
        float(raw)
        return raw
    except ValueError:
        return "'" + raw.replace("'", "''") + "'"


@dataclass(frozen=True)
class TransformationStep:
    """One declared transformation step (§8 output shape)."""

    op: str
    op_version: str = TRANSFORM_MODEL_VERSION
    params: tuple[tuple[str, Any], ...] = ()
    input_refs: tuple[str, ...] = ()
    output_ref: str = ""
    executor: str = "qgis-processing"

    def param_map(self) -> dict[str, Any]:
        return dict(self.params)


@dataclass(frozen=True)
class TransformationChain:
    """Bounded ordered chain of steps with provenance-ready identity."""

    steps: tuple[TransformationStep, ...]
    chain_id: str = ""

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("TransformationChain requires at least one step")


def validate_filter_predicate(predicate: dict[str, Any]) -> list[str]:
    """Validate a filter predicate mapping. Empty = valid."""
    errors: list[str] = []
    if not isinstance(predicate, dict):
        return ["predicate must be an object"]
    for key in ("field", "op"):
        if key not in predicate:
            errors.append(f"predicate.{key}: required field missing")
        elif not isinstance(predicate[key], str) or not predicate[key]:
            errors.append(f"predicate.{key}: must be a non-empty string")
    op = predicate.get("op")
    if isinstance(op, str) and op not in FILTER_OPERATORS:
        errors.append(f"predicate.op: unsupported operator {op!r}")
    if "value" in predicate and not isinstance(predicate["value"], str):
        errors.append("predicate.value: must be a string")
    return errors


def validate_step(op: str, params: dict[str, Any], input_refs: tuple[str, ...]) -> list[str]:
    """Validate one step's op + params + input refs. Empty = valid."""
    errors: list[str] = []
    if op not in PARAM_SCHEMAS:
        return [f"op: unsupported transformation {op!r}"]
    schema = PARAM_SCHEMAS[op]
    required = schema.get("required", [])
    allowed = set(schema.get("properties", {}).keys())
    for name in required:
        if name not in params:
            errors.append(f"params.{name}: required field missing")
    for key, value in params.items():
        if key not in allowed:
            errors.append(f"params.{key}: unexpected field (additionalProperties: false)")
            continue
        expected = schema["properties"][key].get("type")
        if expected == "string" and not isinstance(value, str):
            errors.append(f"params.{key}: expected string, got {type(value).__name__}")
        elif expected == "number" and not isinstance(value, (int, float)):
            errors.append(f"params.{key}: expected number, got {type(value).__name__}")
    if op == TransformOp.FILTER.value:
        errors.extend(
            validate_filter_predicate(
                {
                    "field": params.get("field", ""),
                    "op": params.get("op", ""),
                    "value": params.get("value", ""),
                }
            )
        )
    if op == TransformOp.JOIN.value:
        join_type = params.get("join_type", "one-to-one")
        if join_type != "one-to-one":
            errors.append("params.join_type: only 'one-to-one' is supported in v1 (1:N rejected)")
    if not input_refs:
        errors.append("input_refs: at least one input reference is required")
    for ref in input_refs:
        if not isinstance(ref, str) or not ref:
            errors.append("input_refs: references must be non-empty strings")
    return errors


def validate_chain(steps: list[dict[str, Any]], *, max_steps: int = MAX_CHAIN_STEPS) -> list[str]:
    """Validate a chain of step mappings. Empty = valid."""
    errors: list[str] = []
    if not steps:
        return ["chain: at least one step is required"]
    if len(steps) > max_steps:
        errors.append(f"chain: {len(steps)} steps exceed max {max_steps} (transform-exceeds-bounds)")
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"chain[{i}]: step must be an object")
            continue
        op = step.get("op", "")
        params = step.get("params", {})
        refs = tuple(step.get("input_refs", ()))
        if not isinstance(params, dict):
            errors.append(f"chain[{i}]: params must be an object")
            continue
        for err in validate_step(op, params, refs):
            errors.append(f"chain[{i}].{err}")
    return errors


def make_step(op: str, params: dict[str, Any], input_refs: tuple[str, ...], output_ref: str) -> TransformationStep:
    """Build a validated TransformationStep (raises ValueError on violation)."""
    errors = validate_step(op, params, tuple(input_refs))
    if errors:
        raise ValueError(f"Invalid transformation step: {'; '.join(errors)}")
    alg_id, alg_version = EXECUTOR_PINS[op]
    return TransformationStep(
        op=op,
        op_version=f"{TRANSFORM_MODEL_VERSION}+{alg_id}@{alg_version}",
        params=tuple(sorted(params.items())),
        input_refs=tuple(input_refs),
        output_ref=output_ref,
        executor="qgis-processing",
    )


def chain_identity(steps: tuple[TransformationStep, ...]) -> str:
    """Deterministic sha256 identity for a chain (no timestamps)."""
    payload = json.dumps(
        [
            {
                "op": s.op,
                "op_version": s.op_version,
                "params": [list(p) for p in s.params],
                "input_refs": list(s.input_refs),
                "output_ref": s.output_ref,
                "executor": s.executor,
            }
            for s in steps
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_preserving(op: str) -> bool:
    return op in PRESERVING_OPS


def requires_derived_provenance(op: str) -> bool:
    return op in TRANSFORMING_OPS


__all__ = [
    "TRANSFORM_MODEL_VERSION",
    "MAX_CHAIN_STEPS",
    "TransformOp",
    "PRESERVING_OPS",
    "TRANSFORMING_OPS",
    "EXECUTOR_PINS",
    "FILTER_OPERATORS",
    "PARAM_SCHEMAS",
    "FilterPredicate",
    "TransformationStep",
    "TransformationChain",
    "validate_filter_predicate",
    "validate_step",
    "validate_chain",
    "make_step",
    "chain_identity",
    "is_preserving",
    "requires_derived_provenance",
]
