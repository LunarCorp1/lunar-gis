"""M4-T07 data fulfillment orchestration (QGIS-free planning).

Implements the §1.1 pipeline at the planning level:

```text
Requirement → Classification → FulfillmentPlan → DataResult (planned)
```

The planner never touches live QGIS objects or the network: it works
over a ``LayerInventory`` snapshot and returns a deterministic
``FulfillmentPlan`` (local layer ref / derivation chain / provider
proposal / missing with sub-reason). Execution happens exclusively
through governed tools (``data.run_transformation``,
``data.download_dataset``); validation through ``data.validate_dataset``.
``DataResult`` records the outcome with provenance linkage.

Local-first order (§15.1): snapshot → requirement → classify → local
fulfill → controlled acquire. The LLM may propose requirements; it
MUST NOT classify — classification output here is computed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from lunar_gis.data.contracts import (
    AvailabilityState,
    ClassificationResult,
    DataRequirement,
    LayerInventory,
    MissingReason,
    classify_requirement,
    parse_requirement,
)

FULFILLMENT_MODEL_VERSION = "1.0"


class FulfillmentKind(str, Enum):
    """Planned fulfillment path."""

    LOCAL_LAYER = "local-layer"
    DERIVATION_CHAIN = "derivation-chain"
    PROVIDER_PROPOSAL = "provider-proposal"
    MISSING = "missing"


@dataclass(frozen=True)
class FulfillmentPlan:
    """Deterministic fulfillment plan for one requirement."""

    requirement_name: str
    kind: FulfillmentKind
    availability: AvailabilityState
    layer_id: str | None = None
    chain: tuple[dict[str, Any], ...] = ()
    provider_id: str | None = None
    missing_reason: str | None = None
    evidence: tuple[str, ...] = ()
    snapshot_id: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class DataResult:
    """Outcome record for one fulfilled requirement."""

    requirement_name: str
    availability: AvailabilityState
    subject_kind: str
    subject_ref: str
    validation_verdict: str
    satisfaction: str
    provenance_ref: str | None = None
    warnings: tuple[str, ...] = ()
    fulfillment_version: str = FULFILLMENT_MODEL_VERSION


def _chain_to_dicts(chain: tuple[Any, ...]) -> tuple[dict[str, Any], ...]:
    out: list[dict[str, Any]] = []
    for step in chain:
        params = dict(step.params) if hasattr(step, "params") else {}
        out.append(
            {
                "op": step.op,
                "op_version": getattr(step, "step_schema_version", "1.0"),
                "params": params,
                "input_refs": list(getattr(step, "input_refs", ())),
                "output_ref": getattr(step, "output_ref", ""),
                "executor": getattr(step, "executor", "qgis-processing"),
            }
        )
    return tuple(out)


def plan_fulfillment(requirement: DataRequirement, inventory: LayerInventory) -> FulfillmentPlan:
    """Compute the fulfillment plan (pure, deterministic)."""
    result: ClassificationResult = classify_requirement(requirement, inventory)
    evidence = tuple(f"{e.layer_id}:{e.check}={'pass' if e.passed else 'fail'}" for e in result.evidence)
    warnings: list[str] = []
    if result.snapshot_truncated:
        warnings.append("truncated-inventory")
    if result.state == AvailabilityState.AVAILABLE:
        return FulfillmentPlan(
            requirement_name=requirement.name,
            kind=FulfillmentKind.LOCAL_LAYER,
            availability=result.state,
            layer_id=result.layer_id,
            evidence=evidence,
            snapshot_id=result.snapshot_id,
            warnings=tuple(warnings),
        )
    if result.state == AvailabilityState.DERIVABLE:
        chain = _chain_to_dicts(result.chain)
        prov = list(result.provisional_reasons)
        return FulfillmentPlan(
            requirement_name=requirement.name,
            kind=FulfillmentKind.DERIVATION_CHAIN,
            availability=result.state,
            layer_id=result.layer_id,
            chain=chain,
            evidence=evidence,
            snapshot_id=result.snapshot_id,
            warnings=tuple(warnings + prov),
        )
    # MISSING: propose a controlled provider for data-side gaps when a
    # provider source is acceptable; local re-query gaps (unknown,
    # invalid, truncated) stay MISSING without proposal.
    provider_id: str | None = None
    if result.missing_reason in (
        MissingReason.NO_LAYER,
        MissingReason.SCHEMA_GAP,
        MissingReason.COVERAGE_GAP,
        MissingReason.CRS_GAP,
    ):
        for source in requirement.acceptable_sources:
            if source.startswith("provider:"):
                provider_id = source.split(":", 1)[1]
                break
    kind = FulfillmentKind.PROVIDER_PROPOSAL if provider_id else FulfillmentKind.MISSING
    return FulfillmentPlan(
        requirement_name=requirement.name,
        kind=kind,
        availability=result.state,
        provider_id=provider_id,
        missing_reason=result.missing_reason.value if result.missing_reason else None,
        evidence=evidence,
        snapshot_id=result.snapshot_id,
        warnings=tuple(warnings),
    )


def plan_from_dicts(requirement_data: dict[str, Any], inventory: LayerInventory) -> FulfillmentPlan:
    """Parse a requirement mapping then plan (raises ValueError)."""
    requirement = parse_requirement(requirement_data)
    return plan_fulfillment(requirement, inventory)


def make_data_result(
    *,
    requirement_name: str,
    availability: AvailabilityState,
    subject_kind: str,
    subject_ref: str,
    validation_verdict: str,
    satisfaction: str,
    provenance_ref: str | None = None,
    warnings: tuple[str, ...] = (),
) -> DataResult:
    return DataResult(
        requirement_name=requirement_name,
        availability=availability,
        subject_kind=subject_kind,
        subject_ref=subject_ref,
        validation_verdict=validation_verdict,
        satisfaction=satisfaction,
        provenance_ref=provenance_ref,
        warnings=warnings,
    )


__all__ = [
    "FULFILLMENT_MODEL_VERSION",
    "FulfillmentKind",
    "FulfillmentPlan",
    "DataResult",
    "plan_fulfillment",
    "plan_from_dicts",
    "make_data_result",
]
