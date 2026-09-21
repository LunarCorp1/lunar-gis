"""M4-T06 provenance audit store (QGIS-free).

Append-only store for ``DataProvenance`` records: in-memory index plus
optional JSONL file persistence. Records are immutable once stored —
no updates, no deletes. Queries are read-only projections.

The store never holds secrets: records carry ids/relpaths/stripped
URLs only (enforced at ``records.make_record`` time).

Stdlib only. No ``qgis.*``, no network.
"""

from __future__ import annotations

import json
import os
from typing import Any

from lunar_gis.provenance.records import (
    DataProvenance,
    provenance_canonical_json,
    provenance_identity,
    validate_provenance,
)


class ProvenanceStore:
    """Append-only provenance audit store."""

    def __init__(self, jsonl_path: str | None = None) -> None:
        self._records: list[DataProvenance] = []
        self._by_identity: dict[str, DataProvenance] = {}
        self._jsonl_path = jsonl_path
        if jsonl_path is not None and os.path.isfile(jsonl_path):
            self._load(jsonl_path)

    def append(self, record: DataProvenance) -> str:
        """Store a validated record. Returns its analytical identity.

        Idempotent on identity: re-appending the same analytical record
        returns the existing identity without duplicating.
        """
        errors = validate_provenance(record)
        if errors:
            raise ValueError(f"Invalid provenance record: {'; '.join(errors)}")
        identity = provenance_identity(record)
        if identity in self._by_identity:
            return identity
        self._records.append(record)
        self._by_identity[identity] = record
        if self._jsonl_path is not None:
            with open(self._jsonl_path, "a", encoding="utf-8") as handle:
                handle.write(provenance_canonical_json(record) + "\n")
        return identity

    def _load(self, path: str) -> None:
        from lunar_gis.provenance.records import (
            ProvenanceLicense,
            ProvenanceOrigin,
            ProvenanceSnapshotPin,
            ProvenanceStatus,
            ProvenanceSubject,
            ProvenanceToolInvocation,
            ProvenanceTransformStep,
            ProvenanceValidation,
        )

        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                record = DataProvenance(
                    subject=ProvenanceSubject(**payload["subject"]),
                    origin=ProvenanceOrigin(**payload["origin"]),
                    license=ProvenanceLicense(**payload["license"]),
                    retrieved_at=payload["retrieved_at"],
                    status=ProvenanceStatus(payload.get("status", "ORIGINAL")),
                    requirement_ref=payload.get("requirement_ref"),
                    validation=(
                        ProvenanceValidation(**payload["validation"]) if payload.get("validation") is not None else None
                    ),
                    source_url=payload.get("source_url"),
                    dataset_version=payload.get("dataset_version"),
                    sha256=payload.get("sha256"),
                    snapshot_pin=(
                        ProvenanceSnapshotPin(
                            snapshot_id=payload["snapshot_pin"]["snapshot_id"],
                            taken_at=payload["snapshot_pin"]["taken_at"],
                            feature_count=payload["snapshot_pin"].get("feature_count"),
                            extent=(
                                tuple(payload["snapshot_pin"]["extent"])
                                if payload["snapshot_pin"].get("extent") is not None
                                else None
                            ),
                            field_list=tuple(tuple(pair) for pair in payload["snapshot_pin"].get("field_list", [])),
                        )
                        if payload.get("snapshot_pin") is not None
                        else None
                    ),
                    crs_authid=payload.get("crs_authid"),
                    transforms=tuple(
                        ProvenanceTransformStep(
                            op=t["op"],
                            op_version=t["op_version"],
                            params=tuple(tuple(p) for p in t.get("params", [])),
                            input_refs=tuple(t.get("input_refs", [])),
                            input_hashes=tuple(t.get("input_hashes", [])),
                            output_ref=t.get("output_ref", ""),
                            executor=t.get("executor", "qgis-processing"),
                        )
                        for t in payload.get("transforms", [])
                    ),
                    tool_invocations=tuple(
                        ProvenanceToolInvocation(**inv) for inv in payload.get("tool_invocations", [])
                    ),
                )
                self.append(record)

    def get(self, identity: str) -> DataProvenance | None:
        return self._by_identity.get(identity)

    def by_subject(self, ref: str) -> tuple[DataProvenance, ...]:
        return tuple(r for r in self._records if r.subject.ref == ref)

    def by_tool(self, tool_name: str) -> tuple[DataProvenance, ...]:
        return tuple(r for r in self._records if any(inv.tool_name == tool_name for inv in r.tool_invocations))

    def by_requirement(self, requirement_ref: str) -> tuple[DataProvenance, ...]:
        return tuple(r for r in self._records if r.requirement_ref == requirement_ref)

    def count(self) -> int:
        return len(self._records)

    def identities(self) -> tuple[str, ...]:
        return tuple(provenance_identity(r) for r in self._records)

    def lineage(self, identity: str) -> dict[str, Any]:
        """Derivation chain for one record (JSON-compatible)."""
        record = self._by_identity.get(identity)
        if record is None:
            return {"identity": identity, "found": False}
        return {
            "identity": identity,
            "found": True,
            "subject": {"kind": record.subject.kind, "ref": record.subject.ref},
            "origin": {
                "kind": record.origin.kind,
                "provider_id": record.origin.provider_id,
                "dataset_id": record.origin.dataset_id,
                "asset_id": record.origin.asset_id,
            },
            "status": record.status.value,
            "transforms": [
                {"op": t.op, "op_version": t.op_version, "output_ref": t.output_ref} for t in record.transforms
            ],
            "license": {"spdx": record.license.spdx, "attribution": record.license.attribution},
            "requirement_ref": record.requirement_ref,
            "validation": (
                {"verdict": record.validation.verdict, "report_ref": record.validation.report_ref}
                if record.validation is not None
                else None
            ),
        }


__all__ = ["ProvenanceStore"]
