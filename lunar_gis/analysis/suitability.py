"""Deterministic suitability engine: weighted linear combination (QGIS-free).

Computes per-unit suitability scores from numeric criterion fields:

- normalization: min-max per field (benefit: higher is better;
  cost: lower is better)
- score: weighted sum with weights summing to 1 (AHP weights plug in
  directly); constant fields and nulls fail closed per-field
- classes: 5 equal-interval labels (Very low … Very high)

Units are plain ``{field: value}`` mappings — feature iteration lives
QGIS-side (tools/Processing); this module is pure math over detached
values plus frozen records with input hashes (M2/M3 precedent).

Frozen: SUITABILITY_MODEL_VERSION, CLASS_LABELS, DIRECTIONS.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

SUITABILITY_MODEL_VERSION = "1.0"
ENGINE_VERSION = "1.0.0"

CLASS_LABELS: tuple[str, ...] = ("Very low", "Low", "Moderate", "High", "Very high")


class Direction(str, Enum):
    BENEFIT = "benefit"  # higher values are more suitable
    COST = "cost"  # lower values are more suitable


@dataclass(frozen=True)
class SuitabilityCriterion:
    field: str
    weight: float
    direction: Direction


@dataclass(frozen=True)
class ScoredUnit:
    key: Any
    score: float
    suitability_class: str
    normalized: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class SuitabilityResult:
    scores: tuple[ScoredUnit, ...]
    excluded_nulls: int
    statistics: dict[str, Any]
    criteria: tuple[SuitabilityCriterion, ...]
    method: str
    engine_version: str
    suitability_model_version: str
    input_hash: str


def _input_hash(units: list[dict[str, Any]], criteria: list[SuitabilityCriterion]) -> str:
    payload = json.dumps(
        {
            "units": units,
            "criteria": [[c.field, c.weight, c.direction.value] for c in criteria],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _classify(score: float) -> str:
    index = min(4, max(0, int(score * 5)))
    if score >= 1.0:
        index = 4
    return CLASS_LABELS[index]


def suitability_wlc(
    units: list[dict[str, Any]],
    criteria: list[SuitabilityCriterion],
    *,
    keys: list[Any] | None = None,
) -> SuitabilityResult:
    """Weighted linear combination over detached unit value dicts.

    Raises ValueError on: empty units/criteria, weights not summing to
    1 (±1e-9), unknown/constant/non-numeric fields. Units with null
    (None) in any criterion field are excluded and counted (never
    silently scored).
    """
    if not units:
        raise ValueError("suitability requires at least one unit")
    if not criteria:
        raise ValueError("suitability requires at least one criterion")
    total_weight = sum(c.weight for c in criteria)
    if abs(total_weight - 1.0) > 1e-9:
        raise ValueError(f"criterion weights must sum to 1, got {total_weight}")
    if keys is not None and len(keys) != len(units):
        raise ValueError("keys length must match units length")
    resolved_keys = list(keys) if keys is not None else list(range(len(units)))

    columns: dict[str, list[float]] = {}
    excluded = 0
    usable: list[tuple[Any, dict[str, Any]]] = []
    for key, unit in zip(resolved_keys, units):
        values: dict[str, Any] = {}
        missing = False
        for criterion in criteria:
            value = unit.get(criterion.field, None)
            if value is None or isinstance(value, bool):
                missing = True
                break
            try:
                values[criterion.field] = float(value)
            except (TypeError, ValueError):
                missing = True
                break
        if missing:
            excluded += 1
            continue
        usable.append((key, values))
        for field, value in values.items():
            columns.setdefault(field, []).append(value)
    if not usable:
        raise ValueError("no scorable units (all excluded on nulls/non-numeric fields)")

    bounds: dict[str, tuple[float, float]] = {}
    for criterion in criteria:
        column = columns.get(criterion.field, [])
        if not column:
            raise ValueError(f"no values for field {criterion.field!r}")
        lo, hi = min(column), max(column)
        if lo == hi:
            raise ValueError(f"field {criterion.field!r} is constant ({lo}); cannot normalize")
        bounds[criterion.field] = (lo, hi)

    scored: list[ScoredUnit] = []
    for key, values in usable:
        normalized: dict[str, float] = {}
        score = 0.0
        for criterion in criteria:
            lo, hi = bounds[criterion.field]
            raw = values[criterion.field]
            if criterion.direction == Direction.BENEFIT:
                norm = (raw - lo) / (hi - lo)
            else:
                norm = (hi - raw) / (hi - lo)
            normalized[criterion.field] = norm
            score += criterion.weight * norm
        score = min(1.0, max(0.0, score))
        scored.append(
            ScoredUnit(
                key=key,
                score=score,
                suitability_class=_classify(score),
                normalized=tuple(sorted(normalized.items())),
            )
        )
    scored.sort(key=lambda s: (-s.score, str(s.key)))
    values_sorted = sorted(s.score for s in scored)
    n = len(values_sorted)
    class_counts = {label: 0 for label in CLASS_LABELS}
    for scored_unit in scored:
        class_counts[scored_unit.suitability_class] += 1
    statistics = {
        "count": n,
        "excluded_nulls": excluded,
        "min": values_sorted[0],
        "max": values_sorted[-1],
        "mean": sum(values_sorted) / n,
        "class_counts": class_counts,
    }
    return SuitabilityResult(
        scores=tuple(scored),
        excluded_nulls=excluded,
        statistics=statistics,
        criteria=tuple(criteria),
        method="wlc-minmax",
        engine_version=ENGINE_VERSION,
        suitability_model_version=SUITABILITY_MODEL_VERSION,
        input_hash=_input_hash(units, criteria),
    )


__all__ = [
    "SUITABILITY_MODEL_VERSION",
    "ENGINE_VERSION",
    "CLASS_LABELS",
    "Direction",
    "SuitabilityCriterion",
    "ScoredUnit",
    "SuitabilityResult",
    "suitability_wlc",
]
