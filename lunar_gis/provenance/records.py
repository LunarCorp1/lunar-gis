"""M4-T06 provenance records (QGIS-free).

Frozen ``DataProvenance v1.0`` shape per M4 §10: the single source of
truth for dataset lineage. ``lunar_gis/data`` emits these records;
this module validates, serializes, and identifies them. The audit
store lives in ``provenance.store`` — this module never stores.

Rules enforced:
- DERIVED requires non-empty ``transforms``; ORIGINAL requires empty
- license ``spdx`` explicit (``NONE-declared`` allowed, never null)
- ``source_url`` is host+path only (query/fragment stripped at build);
  signed URLs (query SAS/signature tokens) are rejected outright
- ``retrieved_at`` is audit metadata (never part of analytical identity)
- no secrets: refs are layer ids / sandbox relpaths; URLs carry no query

Stdlib only. No ``qgis.*``, no network, no ``project``/``agent``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import urlsplit

PROVENANCE_MODEL_VERSION = "1.0"

SUBJECT_KINDS: frozenset[str] = frozenset({"layer-ref", "file"})
ORIGIN_KINDS: frozenset[str] = frozenset({"project", "local-file", "provider"})
VALIDATION_VERDICTS: frozenset[str] = frozenset({"VALID", "EMPTY", "INVALID"})


class ProvenanceStatus(str, Enum):
    ORIGINAL = "ORIGINAL"
    DERIVED = "DERIVED"


@dataclass(frozen=True)
class ProvenanceSubject:
    kind: str  # layer-ref | file
    ref: str  # layer_id | sandbox_relpath (never absolute secrets)


@dataclass(frozen=True)
class ProvenanceOrigin:
    kind: str  # project | local-file | provider
    provider_id: str | None = None
    provider_version: str | None = None
    dataset_id: str | None = None
    asset_id: str | None = None


@dataclass(frozen=True)
class ProvenanceValidation:
    verdict: str  # VALID | EMPTY | INVALID
    report_ref: str  # sha256 identity of the ValidationReport


@dataclass(frozen=True)
class ProvenanceLicense:
    spdx: str  # SPDX id or "NONE-declared" (explicit, never null)
    attribution: str = ""


@dataclass(frozen=True)
class ProvenanceSnapshotPin:
    snapshot_id: str
    taken_at: str
    feature_count: int | None = None
    extent: tuple[float, float, float, float] | None = None
    field_list: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ProvenanceTransformStep:
    op: str
    op_version: str
    params: tuple[tuple[str, Any], ...] = ()
    input_refs: tuple[str, ...] = ()
    input_hashes: tuple[str, ...] = ()
    output_ref: str = ""
    executor: str = "qgis-processing"


@dataclass(frozen=True)
class ProvenanceToolInvocation:
    tool_name: str
    tool_version: str
    policy_decision_ref: str = ""


@dataclass(frozen=True)
class DataProvenance:
    """Frozen minimum provenance record (M4 §10)."""

    subject: ProvenanceSubject
    origin: ProvenanceOrigin
    license: ProvenanceLicense
    retrieved_at: str  # ISO-8601 UTC audit timestamp
    status: ProvenanceStatus = ProvenanceStatus.ORIGINAL
    requirement_ref: str | None = None
    validation: ProvenanceValidation | None = None
    source_url: str | None = None
    dataset_version: str | None = None
    sha256: str | None = None
    snapshot_pin: ProvenanceSnapshotPin | None = None
    crs_authid: str | None = None
    transforms: tuple[ProvenanceTransformStep, ...] = ()
    tool_invocations: tuple[ProvenanceToolInvocation, ...] = ()
    provenance_version: str = PROVENANCE_MODEL_VERSION


_SIGNED_MARKERS: tuple[str, ...] = ("sig=", "signature=", "token=", "sas=", "se=", "sp=", "sv=")


def strip_source_url(url: str) -> str | None:
    """Reduce a source URL to host+path. None when signed/non-http.

    Signed URLs (query carries SAS/signature/token markers) are rejected
    outright — stored ``source_url`` must never leak credentials.
    """
    if not isinstance(url, str) or not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    query = (parts.query or "").lower()
    if any(marker in query for marker in _SIGNED_MARKERS):
        return None
    path = parts.path or "/"
    return f"{parts.scheme}://{parts.hostname}{path}"


def validate_provenance(record: DataProvenance) -> list[str]:
    """Validate a provenance record. Empty = valid."""
    errors: list[str] = []
    if record.subject.kind not in SUBJECT_KINDS:
        errors.append(f"subject.kind: unsupported {record.subject.kind!r}")
    if not record.subject.ref:
        errors.append("subject.ref: must be non-empty")
    if record.origin.kind not in ORIGIN_KINDS:
        errors.append(f"origin.kind: unsupported {record.origin.kind!r}")
    if record.origin.kind == "provider":
        for attr in ("provider_id", "provider_version", "dataset_id"):
            if not getattr(record.origin, attr):
                errors.append(f"origin.{attr}: required for provider origin")
    if not record.license.spdx:
        errors.append("license.spdx: must be explicit (use NONE-declared)")
    if record.validation is not None and record.validation.verdict not in VALIDATION_VERDICTS:
        errors.append(f"validation.verdict: unsupported {record.validation.verdict!r}")
    if record.status == ProvenanceStatus.DERIVED and not record.transforms:
        errors.append("transforms: DERIVED requires a non-empty transform chain")
    if record.status == ProvenanceStatus.ORIGINAL and record.transforms:
        errors.append("transforms: ORIGINAL must not carry a transform chain")
    if record.source_url is not None:
        stripped = strip_source_url(record.source_url)
        if stripped is None:
            errors.append("source_url: must be an unsigned http(s) URL (host+path stored)")
        elif stripped != record.source_url:
            errors.append("source_url: must already be stripped to host+path")
    if record.sha256 is not None and (
        len(record.sha256) != 64 or any(c not in "0123456789abcdef" for c in record.sha256)
    ):
        errors.append("sha256: must be 64 lowercase hex chars")
    return errors


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (ProvenanceSubject, ProvenanceOrigin, ProvenanceValidation)):
        return _to_jsonable(value.__dict__)
    if isinstance(value, (ProvenanceLicense, ProvenanceSnapshotPin)):
        return _to_jsonable(value.__dict__)
    if isinstance(value, (ProvenanceTransformStep, ProvenanceToolInvocation, DataProvenance)):
        return _to_jsonable(value.__dict__)
    return value


def provenance_to_dict(record: DataProvenance) -> dict[str, Any]:
    """JSON-compatible dict with Nones omitted (deterministic key order)."""
    raw = _to_jsonable(record.__dict__)
    return {k: v for k, v in raw.items() if v is not None}


def provenance_canonical_json(record: DataProvenance) -> str:
    """Canonical JSON (sorted keys) — the hashable form."""
    return json.dumps(provenance_to_dict(record), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def provenance_identity(record: DataProvenance) -> str:
    """sha256 over canonical JSON excluding the audit timestamp.

    Analytical identity must not break on ``retrieved_at`` (same envelope
    philosophy as M3-T04 §7.4): two records differing only in retrieval
    time share one identity.
    """
    payload = provenance_to_dict(record)
    payload.pop("retrieved_at", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def make_record(
    *,
    subject_kind: str,
    subject_ref: str,
    origin_kind: str,
    license_spdx: str,
    retrieved_at: str,
    status: ProvenanceStatus = ProvenanceStatus.ORIGINAL,
    **kwargs: Any,
) -> DataProvenance:
    """Build a validated DataProvenance (raises ValueError on violation)."""
    record = DataProvenance(
        subject=ProvenanceSubject(kind=subject_kind, ref=subject_ref),
        origin=ProvenanceOrigin(
            kind=origin_kind,
            provider_id=kwargs.get("provider_id"),
            provider_version=kwargs.get("provider_version"),
            dataset_id=kwargs.get("dataset_id"),
            asset_id=kwargs.get("asset_id"),
        ),
        license=ProvenanceLicense(spdx=license_spdx, attribution=kwargs.get("attribution", "")),
        retrieved_at=retrieved_at,
        status=status,
        requirement_ref=kwargs.get("requirement_ref"),
        validation=kwargs.get("validation"),
        source_url=kwargs.get("source_url"),
        dataset_version=kwargs.get("dataset_version"),
        sha256=kwargs.get("sha256"),
        snapshot_pin=kwargs.get("snapshot_pin"),
        crs_authid=kwargs.get("crs_authid"),
        transforms=tuple(kwargs.get("transforms", ())),
        tool_invocations=tuple(kwargs.get("tool_invocations", ())),
    )
    errors = validate_provenance(record)
    if errors:
        raise ValueError(f"Invalid provenance record: {'; '.join(errors)}")
    return record


__all__ = [
    "PROVENANCE_MODEL_VERSION",
    "ProvenanceStatus",
    "ProvenanceSubject",
    "ProvenanceOrigin",
    "ProvenanceValidation",
    "ProvenanceLicense",
    "ProvenanceSnapshotPin",
    "ProvenanceTransformStep",
    "ProvenanceToolInvocation",
    "DataProvenance",
    "strip_source_url",
    "validate_provenance",
    "provenance_to_dict",
    "provenance_canonical_json",
    "provenance_identity",
    "make_record",
]
