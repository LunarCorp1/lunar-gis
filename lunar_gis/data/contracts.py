"""M4-T02 data contracts: QGIS-free frozen shapes for the Data Engine.

Implements the contract layer frozen in docs/research/M4-DATA-ENGINE-DESIGN.md
(§§1-4, 7, 8, 10) and ADR-0012:

- LayerRecord / LayerInventory snapshot representation (§2)
- DataRequirement v1.0 with validator-compatible shapes (§4)
- Deterministic AVAILABLE / DERIVABLE / MISSING classification (§3)
- TransformationStep records (declared, never executed) (§8)
- Snapshot pinning + source redaction / path minimization (§10, §2.1)

This module is pure Python stdlib. It imports nothing from lunar_gis
(deliberately — not even utils/provenance — so the QGIS-free property
cannot regress on a transitive import), no qgis, no network, no I/O,
no eval/exec/subprocess/pickle. Deterministic: same inputs → same outputs;
no timestamps except explicitly envelope-only values passed in by callers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence


# ---------------------------------------------------------------------------
# Versions and frozen configuration
# ---------------------------------------------------------------------------

REQUIREMENT_VERSION = "1.0"
STEP_SCHEMA_VERSION = "1.0"

# Implementation config (non-normative) per M4-T01 §16: only chain *length*
# is evaluated against bounds until numeric caps are frozen.
MAX_CHAIN_STEPS = 3

INVENTORY_TRUNCATION_CAP = 500

# Closed transformation op set, M4-T01 §8. Order is normative: it is the
# tie-break order for DERIVABLE chain selection (§3.2).
TRANSFORM_OPS: tuple[str, ...] = (
    "reproject-vector",
    "reproject-raster",
    "clip",
    "filter",
    "join",
    "raster-to-vector",
    "vector-to-raster",
)

# Ops the v1 classifier may emit. clip/filter are valid closed-set members
# (accepted in schemas and TransformationStep.op) but are never emitted by
# v1 enumeration: a satisfied clip precondition already classifies
# AVAILABLE (full containment), partial-coverage inputs stay MISSING by the
# no-merge rule (§8), and filter row predicates are not representable in
# DataRequirement v1.0.
EMIT_OPS: tuple[str, ...] = (
    "reproject-vector",
    "reproject-raster",
    "join",
    "raster-to-vector",
    "vector-to-raster",
)

REQUIREMENT_GEOMETRIES: tuple[str, ...] = (
    "Any",
    "Point",
    "LineString",
    "Polygon",
    "Raster",
    "Table",
)

CANONICAL_GEOMETRIES: tuple[str, ...] = (
    "Point",
    "LineString",
    "Polygon",
    "Raster",
    "Table",
    "Unknown",
)

# Closed QVariant subset, M4-T01 §4. Unlisted → requirement INVALID.
QVARIANT_SUBSET: frozenset[str] = frozenset({"String", "Int", "Double", "Date", "DateTime", "Bool", "StringList"})

# Provider field-type normalization (frozen string table, QGIS-free).
# Discovery records provider type names verbatim (e.g. lowercase "integer"
# from OGR/memory providers); comparison normalizes to the closed subset
# first. Unmapped names survive verbatim and then fail the closed-subset
# check (schema-gap) — never guessed, never crashed on.
FIELD_TYPE_NORMALIZATION: dict[str, str] = {
    "string": "String",
    "str": "String",
    "qstring": "String",
    "text": "String",
    "int": "Int",
    "integer": "Int",
    "long": "Int",
    "short": "Int",
    "int64": "Int",
    "double": "Double",
    "float": "Double",
    "real": "Double",
    "numeric": "Double",
    "date": "Date",
    "datetime": "DateTime",
    "timestamp": "DateTime",
    "time": "DateTime",
    "bool": "Bool",
    "boolean": "Bool",
    "qstringlist": "StringList",
    "stringlist": "StringList",
}

# Frozen coercion allowlist: exact-type match + Int→Double widening only.
COERCIBLE: frozenset[tuple[str, str]] = frozenset(
    {
        ("String", "String"),
        ("Int", "Int"),
        ("Double", "Double"),
        ("Date", "Date"),
        ("DateTime", "DateTime"),
        ("Bool", "Bool"),
        ("StringList", "StringList"),
        ("Int", "Double"),
    }
)

REQUIREMENT_SOURCES: frozenset[str] = frozenset({"local-project", "local-file"})
PROVIDER_ID_PATTERN = re.compile(r"^provider:[A-Za-z0-9][A-Za-z0-9._-]*$")

# Provider prefix → storage kind. Unknown prefixes → "unknown" (never guessed).
PROVIDER_STORAGE: dict[str, str] = {
    "memory": "memory",
    "ogr": "file",
    "gdal": "file",
    "delimitedtext": "file",
    "spatialite": "database",
    "postgres": "database",
    "mssql": "database",
    "oracle": "database",
    "wfs": "remote-service",
    "wms": "remote-service",
    "wcs": "remote-service",
    "arcgisfeatureserver": "remote-service",
    "arcgismapserver": "remote-service",
}

# Fixed AVAILABLE check order, M4-T01 §3.1 (+ temporal trailing, §4).
CHECK_ORDER: tuple[str, ...] = (
    "geometry",
    "fields",
    "crs",
    "reachability",
    "coverage",
    "validity",
    "temporal",
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DataContractErrorCode(str, Enum):
    """Stable error codes for contract validation failures."""

    INVALID_REQUIREMENT = "INVALID_REQUIREMENT"
    INVALID_INVENTORY = "INVALID_INVENTORY"


class DataContractError(ValueError):
    """Deterministic contract validation error with a stable code."""

    def __init__(self, code: DataContractErrorCode | str, message: str) -> None:
        if isinstance(code, str):
            code = DataContractErrorCode(code)
        self.code = code
        super().__init__(f"[{code.value}] {message}")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ValueState(str, Enum):
    """Three-state representation for nullable discovery values (§2.2)."""

    KNOWN = "known"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class StorageKind(str, Enum):
    """Where a layer's bytes live (§2.1)."""

    MEMORY = "memory"
    FILE = "file"
    DATABASE = "database"
    REMOTE_SERVICE = "remote-service"
    UNKNOWN = "unknown"


class Reachability(str, Enum):
    """Reachability knowledge without probing (§2.1)."""

    KNOWN_REACHABLE = "known-reachable"
    KNOWN_UNREACHABLE = "known-unreachable"
    UNKNOWN = "unknown"


class AvailabilityState(str, Enum):
    """Classification verdicts (ADR-0003, M4-T01 §3)."""

    AVAILABLE = "available"
    DERIVABLE = "derivable"
    MISSING = "missing"


class MissingReason(str, Enum):
    """Machine-readable MISSING sub-reasons, snapshot scope (§3.3).

    v1 snapshot scope only: provider-offline / license-unavailable are
    acquisition-scope reasons (design §6 mapping) owned by provider tasks,
    never emitted by classify_requirement in v1 (pinned by test).
    """

    NO_LAYER = "no-layer"
    SCHEMA_GAP = "schema-gap"
    CRS_GAP = "crs-gap"
    COVERAGE_GAP = "coverage-gap"
    UNKNOWN_DEFERRED = "unknown-deferred"
    INVALID_CANDIDATE = "invalid-candidate"
    TRUNCATED_INVENTORY = "truncated-inventory"
    TRANSFORM_EXCEEDS_BOUNDS = "transform-exceeds-bounds"


class VerificationState(str, Enum):
    """Output-only requirement verification (§4)."""

    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    PARTIAL = "partial"


# ---------------------------------------------------------------------------
# Snapshot shapes (§2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LayerField:
    """One vector attribute: name + QVariant type name (opaque at discovery)."""

    name: str
    type: str


@dataclass(frozen=True)
class LayerExtent:
    """Bounding box + the CRS its coordinates are expressed in."""

    xmin: float
    ymin: float
    xmax: float
    ymax: float
    crs_authid: str


@dataclass(frozen=True)
class LayerRecord:
    """One snapshotted layer. Nullable discovery values carry explicit states."""

    layer_id: str
    name: str
    provider: str
    geometry_type: str | None  # opaque QGIS repr; None = absent (raster/table)
    crs_authid: str | None  # None = unknown; "" normalized to None at discovery
    crs_known: bool
    feature_count: int | None  # None unless feature_count_state == KNOWN
    feature_count_state: ValueState
    extent: LayerExtent | None
    extent_state: ValueState
    extent_unavailable_reason: str | None = None
    fields: tuple[LayerField, ...] | None = None
    fields_state: ValueState = ValueState.UNKNOWN
    fields_unavailable_reason: str | None = None
    source_redacted: str = ""
    storage: StorageKind = StorageKind.UNKNOWN
    reachable: Reachability = Reachability.UNKNOWN
    has_time: bool | None = None
    valid: bool = False


@dataclass(frozen=True)
class LayerInventory:
    """Deterministic project snapshot (§1.3). Records sorted by layer_id."""

    records: tuple[LayerRecord, ...]
    snapshot_id: str
    taken_at: str  # ISO-8601 UTC envelope timestamp (never in verdicts)
    project_dirty: bool
    total_count: int
    truncated: bool

    def __post_init__(self) -> None:
        """Enforce layer_id ordering structurally (design §1.3 invariant)."""
        ordered = tuple(sorted(self.records, key=lambda r: r.layer_id))
        if ordered != self.records:
            object.__setattr__(self, "records", ordered)


@dataclass(frozen=True)
class SnapshotPin:
    """Reproducibility pin for a snapshot (§10)."""

    snapshot_id: str
    taken_at: str
    record_count: int
    truncated: bool


# ---------------------------------------------------------------------------
# Requirement shape (§4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DataRequirement:
    """DataRequirement v1.0. Absent optional = unconstrained (no null unions)."""

    name: str
    geometry: str = "Any"
    required_fields: tuple[str, ...] = ()
    field_types: tuple[tuple[str, str], ...] = ()
    crs_authid: str | None = None  # None (absent) = any CRS
    extent: LayerExtent | None = None  # None (absent) = no coverage constraint
    coverage_threshold: float = 1.0  # fraction in (0,1]; ignored if extent absent
    has_time: bool | None = None
    acceptable_sources: tuple[str, ...] = ("local-project", "local-file")
    transformations_allowed: tuple[str, ...] = TRANSFORM_OPS
    requirement_version: str = REQUIREMENT_VERSION

    def field_type_map(self) -> dict[str, str]:
        """field_types pairs as a dict (insertion order = sorted input order)."""
        return dict(self.field_types)


# ---------------------------------------------------------------------------
# Classification + transformation shapes (§§3, 8)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckEvidence:
    """One predicate check outcome for one layer."""

    layer_id: str
    check: str  # one of CHECK_ORDER
    passed: bool
    detail: str


@dataclass(frozen=True)
class TransformationStep:
    """Declared (never executed) transformation step (§8)."""

    op: str  # one of TRANSFORM_OPS
    step_schema_version: str  # "1.0"; versions this shape, not the executor
    executor: str  # "qgis-processing"; algorithm pin resolved at execution
    executor_alg_ref: str | None  # None at classify time (provisional)
    params: tuple[tuple[str, Any], ...]  # fully specified, sorted by key
    input_refs: tuple[str, ...]  # layer_ids (or derived refs for chained steps)
    output_ref: str  # symbolic derived ref; lifecycle resolved at execution
    provisional: bool
    provisional_reasons: tuple[str, ...] = ()

    def params_dict(self) -> dict[str, Any]:
        """params pairs as a dict."""
        return dict(self.params)


@dataclass(frozen=True)
class ClassificationResult:
    """Deterministic classification verdict (§3). No timestamps inside."""

    state: AvailabilityState
    requirement_name: str
    layer_id: str | None  # fulfilling layer (AVAILABLE) or primary input
    evidence: tuple[CheckEvidence, ...]  # CHECK_ORDER per evaluated layer
    missing_reason: MissingReason | None
    chain: tuple[TransformationStep, ...]  # empty unless DERIVABLE
    provisional: bool
    provisional_reasons: tuple[str, ...]
    snapshot_id: str
    snapshot_truncated: bool


# ---------------------------------------------------------------------------
# Redaction / minimization (§10, §2.1). Stdlib only, no I/O.
# ---------------------------------------------------------------------------

_CREDENTIALS_PATTERN = re.compile(r"(://[^/@\s]+)@")
_HOME: str = os.path.expanduser("~")


def redact_source(source: str) -> str:
    """Strip credentials from a provider connection string.

    Removes ``user[:pass]@`` authority prefixes and collapses the local
    home directory to ``~``. Never logs or returns secrets (AGENTS.md:10).
    Pure string handling: no I/O, no network.
    """
    if not isinstance(source, str):
        return ""
    redacted = _CREDENTIALS_PATTERN.sub("://", source)
    home = _HOME
    if home and home != "~" and redacted.startswith(home):
        redacted = "~" + redacted[len(home) :]
    return redacted


def minimize_path(path: str) -> str:
    """Collapse a filesystem path for display/provenance (no expansion)."""
    if not isinstance(path, str) or not path:
        return ""
    home = _HOME
    if home and home != "~" and path.startswith(home):
        return "~" + path[len(home) :]
    return path


# ---------------------------------------------------------------------------
# Geometry canonicalization (§7 mapping applied QGIS-free to opaque strings)
# ---------------------------------------------------------------------------


def canonicalize_geometry(opaque: str | None) -> str:
    """Map an opaque discovery geometry string to the canonical enum.

    Total function (frozen table): every input yields a member of
    CANONICAL_GEOMETRIES. Name matching is case-insensitive with
    Multi*/Z/M variants folding into their family. Digit strings follow
    the QGIS 3/4 ``geometryType()`` numbering — verified on QGIS 4.2.0
    (``Qgis.GeometryType``: Point=0, Line=1, Polygon=2, Unknown=3,
    Null=4; ``str()`` yields the int, not the name): 0→Point, 1→LineString,
    2→Polygon, 3→Unknown, 4→Unknown. Unknown/absent input yields
    "Unknown" (satisfies only an "Any" requirement — UNKNOWN is never
    promoted to usable data).
    """
    if opaque is None:
        return "Unknown"
    text = str(opaque).strip().lower()
    if not text or text in {"unknown", "null", "none", "nogeometry"}:
        return "Unknown"
    if "polygon" in text:
        return "Polygon"
    if "line" in text:
        return "LineString"
    if "point" in text:
        return "Point"
    if text in {"0"}:
        return "Point"
    if text in {"1"}:
        return "LineString"
    if text in {"2"}:
        return "Polygon"
    if text in {"3", "4"}:
        return "Unknown"
    if "raster" in text:
        return "Raster"
    if "table" in text:
        return "Table"
    return "Unknown"


def normalize_field_type(name: str) -> str:
    """Map a provider field-type name onto the closed QVariant subset.

    Already-canonical names pass through; known aliases fold
    case-insensitively; anything else survives verbatim so it fails the
    closed-subset check downstream (schema-gap) instead of being guessed.
    """
    if not isinstance(name, str):
        return ""
    key = name.strip().lower()
    if not key:
        return ""
    canonical = FIELD_TYPE_NORMALIZATION.get(key)
    if canonical is not None:
        return canonical
    if name in QVARIANT_SUBSET:
        return name
    return name


def geometry_satisfies(requirement_geometry: str, canonical: str) -> bool:
    """Typed requirement needs canonical equality; "Any" matches everything."""
    if requirement_geometry == "Any":
        return True
    return requirement_geometry == canonical


# ---------------------------------------------------------------------------
# Requirement parsing / validation (§4, validator-compatible)
# ---------------------------------------------------------------------------

_REQUIREMENT_KEYS: frozenset[str] = frozenset(
    {
        "name",
        "geometry",
        "required_fields",
        "field_types",
        "crs",
        "extent",
        "coverage_threshold",
        "temporal",
        "acceptable_sources",
        "transformations_allowed",
    }
)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse_requirement(data: dict[str, Any]) -> DataRequirement:
    """Validate a requirement dict and build a DataRequirement.

    Enforces the full §4 checklist: known keys only (additionalProperties
    false equivalent — this is also the LLM-label-ignored enforcement: any
    proposer-supplied label/classification key is rejected), closed enums
    via custom checks, extent validity, coverage range, provider-id
    pattern, closed QVariant subset + frozen coercion note, and the
    two-schema verification rule (present ``verification`` → rejected).
    Applies documented defaults. Raises DataContractError (never silent).
    """
    if not isinstance(data, dict):
        raise DataContractError(
            DataContractErrorCode.INVALID_REQUIREMENT,
            f"requirement must be an object, got {type(data).__name__}",
        )
    unknown_keys = sorted(set(data.keys()) - _REQUIREMENT_KEYS - {"verification"})
    if "verification" in data:
        raise DataContractError(
            DataContractErrorCode.INVALID_REQUIREMENT,
            "verification is output-only and must be absent on input",
        )
    if unknown_keys:
        raise DataContractError(
            DataContractErrorCode.INVALID_REQUIREMENT,
            f"unknown fields rejected: {unknown_keys}",
        )

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise DataContractError(
            DataContractErrorCode.INVALID_REQUIREMENT,
            "name must be a non-empty string",
        )

    geometry = data.get("geometry", "Any")
    if geometry not in REQUIREMENT_GEOMETRIES:
        raise DataContractError(
            DataContractErrorCode.INVALID_REQUIREMENT,
            f"geometry must be one of {list(REQUIREMENT_GEOMETRIES)}, got {geometry!r}",
        )

    required_fields = data.get("required_fields", [])
    if not isinstance(required_fields, list) or any(not isinstance(f, str) or not f for f in required_fields):
        raise DataContractError(
            DataContractErrorCode.INVALID_REQUIREMENT,
            "required_fields must be a list of non-empty strings",
        )

    field_types = data.get("field_types", {})
    if not isinstance(field_types, dict):
        raise DataContractError(
            DataContractErrorCode.INVALID_REQUIREMENT,
            "field_types must be an object mapping field name to type name",
        )
    for key, value in field_types.items():
        if not isinstance(key, str) or not key:
            raise DataContractError(
                DataContractErrorCode.INVALID_REQUIREMENT,
                f"field_types keys must be non-empty strings, got {key!r}",
            )
        if value not in QVARIANT_SUBSET:
            raise DataContractError(
                DataContractErrorCode.INVALID_REQUIREMENT,
                f"field_types[{key!r}] must be one of {sorted(QVARIANT_SUBSET)}, got {value!r}",
            )

    crs_authid: str | None = None
    if "crs" in data:
        crs = data["crs"]
        if not isinstance(crs, dict) or set(crs.keys()) != {"authid"}:
            raise DataContractError(
                DataContractErrorCode.INVALID_REQUIREMENT,
                "crs must be an object with exactly {authid}",
            )
        if not isinstance(crs["authid"], str) or not crs["authid"].strip():
            raise DataContractError(
                DataContractErrorCode.INVALID_REQUIREMENT,
                "crs.authid must be a non-empty string",
            )
        crs_authid = crs["authid"]

    extent: LayerExtent | None = None
    if "extent" in data:
        raw = data["extent"]
        if not isinstance(raw, dict) or set(raw.keys()) != {
            "xmin",
            "ymin",
            "xmax",
            "ymax",
            "crs_authid",
        }:
            raise DataContractError(
                DataContractErrorCode.INVALID_REQUIREMENT,
                "extent must be an object with exactly {xmin, ymin, xmax, ymax, crs_authid}",
            )
        for axis in ("xmin", "ymin", "xmax", "ymax"):
            if not _is_number(raw[axis]):
                raise DataContractError(
                    DataContractErrorCode.INVALID_REQUIREMENT,
                    f"extent.{axis} must be a number, got {raw[axis]!r}",
                )
        if not isinstance(raw["crs_authid"], str) or not raw["crs_authid"].strip():
            raise DataContractError(
                DataContractErrorCode.INVALID_REQUIREMENT,
                "extent.crs_authid must be a non-empty string",
            )
        if not raw["xmin"] < raw["xmax"]:
            raise DataContractError(
                DataContractErrorCode.INVALID_REQUIREMENT,
                "extent requires xmin < xmax",
            )
        if not raw["ymin"] < raw["ymax"]:
            raise DataContractError(
                DataContractErrorCode.INVALID_REQUIREMENT,
                "extent requires ymin < ymax",
            )
        extent = LayerExtent(
            xmin=float(raw["xmin"]),
            ymin=float(raw["ymin"]),
            xmax=float(raw["xmax"]),
            ymax=float(raw["ymax"]),
            crs_authid=raw["crs_authid"],
        )

    coverage_threshold = data.get("coverage_threshold", 1.0)
    if not _is_number(coverage_threshold) or not 0.0 < float(coverage_threshold) <= 1.0:
        raise DataContractError(
            DataContractErrorCode.INVALID_REQUIREMENT,
            f"coverage_threshold must be a number in (0, 1], got {coverage_threshold!r}",
        )

    has_time: bool | None = None
    if "temporal" in data:
        temporal = data["temporal"]
        if not isinstance(temporal, dict) or set(temporal.keys()) != {"has_time"}:
            raise DataContractError(
                DataContractErrorCode.INVALID_REQUIREMENT,
                "temporal must be an object with exactly {has_time}",
            )
        if not isinstance(temporal["has_time"], bool):
            raise DataContractError(
                DataContractErrorCode.INVALID_REQUIREMENT,
                "temporal.has_time must be a boolean",
            )
        has_time = temporal["has_time"]

    acceptable_sources = data.get("acceptable_sources", ["local-project", "local-file"])
    if not isinstance(acceptable_sources, list) or not acceptable_sources:
        raise DataContractError(
            DataContractErrorCode.INVALID_REQUIREMENT,
            "acceptable_sources must be a non-empty list",
        )
    for source in acceptable_sources:
        if source in REQUIREMENT_SOURCES:
            continue
        if isinstance(source, str) and PROVIDER_ID_PATTERN.match(source):
            continue
        raise DataContractError(
            DataContractErrorCode.INVALID_REQUIREMENT,
            f"acceptable_sources entries must be local-project, local-file, or provider:<id>, got {source!r}",
        )

    transformations_allowed = data.get("transformations_allowed", list(TRANSFORM_OPS))
    if not isinstance(transformations_allowed, list) or any(op not in TRANSFORM_OPS for op in transformations_allowed):
        raise DataContractError(
            DataContractErrorCode.INVALID_REQUIREMENT,
            f"transformations_allowed must be a list of {list(TRANSFORM_OPS)}",
        )

    return DataRequirement(
        name=name,
        geometry=geometry,
        required_fields=tuple(required_fields),
        field_types=tuple(sorted(field_types.items())),
        crs_authid=crs_authid,
        extent=extent,
        coverage_threshold=float(coverage_threshold),
        has_time=has_time,
        acceptable_sources=tuple(acceptable_sources),
        transformations_allowed=tuple(transformations_allowed),
    )


def requirement_to_dict(requirement: DataRequirement) -> dict[str, Any]:
    """Serialize a DataRequirement to a plain JSON-compatible dict.

    Absent optionals are omitted (absence pattern); field order is fixed.
    """
    output: dict[str, Any] = {
        "name": requirement.name,
        "geometry": requirement.geometry,
        "required_fields": list(requirement.required_fields),
    }
    if requirement.field_types:
        output["field_types"] = dict(requirement.field_types)
    if requirement.crs_authid is not None:
        output["crs"] = {"authid": requirement.crs_authid}
    if requirement.extent is not None:
        output["extent"] = {
            "xmin": requirement.extent.xmin,
            "ymin": requirement.extent.ymin,
            "xmax": requirement.extent.xmax,
            "ymax": requirement.extent.ymax,
            "crs_authid": requirement.extent.crs_authid,
        }
    if requirement.coverage_threshold != 1.0:
        output["coverage_threshold"] = requirement.coverage_threshold
    if requirement.has_time is not None:
        output["temporal"] = {"has_time": requirement.has_time}
    output["acceptable_sources"] = list(requirement.acceptable_sources)
    output["transformations_allowed"] = list(requirement.transformations_allowed)
    return output


def requirement_canonical_json(requirement: DataRequirement) -> str:
    """Deterministic canonical JSON for a requirement (sorted keys)."""
    return json.dumps(
        requirement_to_dict(requirement),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Snapshot identity (§1.3)
# ---------------------------------------------------------------------------


def compute_snapshot_id(layer_ids: Sequence[str], taken_at: str) -> str:
    """sha256 over canonical JSON of ordered layer_ids + taken_at."""
    payload = {"layer_ids": list(layer_ids), "taken_at": taken_at}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def snapshot_pin(inventory: LayerInventory) -> SnapshotPin:
    """Build the reproducibility pin for an inventory (§10)."""
    return SnapshotPin(
        snapshot_id=inventory.snapshot_id,
        taken_at=inventory.taken_at,
        record_count=len(inventory.records),
        truncated=inventory.truncated,
    )


# ---------------------------------------------------------------------------
# Classification predicate (§3). QGIS-free, snapshot-only, deterministic.
# ---------------------------------------------------------------------------


def _type_compatible(layer_type: str, required_type: str) -> bool:
    """Frozen coercion allowlist: exact-type match + Int→Double only.

    Provider type names are normalized to the closed QVariant subset
    first; unmapped names fail (schema-gap) instead of being guessed.
    """
    return (normalize_field_type(layer_type), required_type) in COERCIBLE


def _bbox_contains_native(outer: LayerExtent, inner: LayerExtent) -> bool | None:
    """ESTIMATE-only same-CRS bbox containment.

    Returns True/False when both boxes share one CRS string, else None
    (unknown — never computed across CRS here; normative coverage is
    QGIS-executed at validation). Labeled ESTIMATE per §3.1.
    """
    if outer.crs_authid != inner.crs_authid:
        return None
    return (
        outer.xmin <= inner.xmin and outer.ymin <= inner.ymin and outer.xmax >= inner.xmax and outer.ymax >= inner.ymax
    )


def _check_layer(requirement: DataRequirement, record: LayerRecord) -> tuple[list[CheckEvidence], str | None]:
    """Run the fixed AVAILABLE check order for one layer.

    Returns (evidence, terminal_failure) where terminal_failure is the
    MissingReason value for this layer's first failed check, or None when
    all checks pass. UNKNOWN states yield "unknown-deferred" and stop the
    layer (UNKNOWN is never promoted to a pass).
    """
    evidence: list[CheckEvidence] = []
    layer_id = record.layer_id

    def record_check(check: str, passed: bool, detail: str) -> None:
        evidence.append(CheckEvidence(layer_id=layer_id, check=check, passed=passed, detail=detail))

    # 1. geometry
    canonical = canonicalize_geometry(record.geometry_type)
    if not geometry_satisfies(requirement.geometry, canonical):
        record_check("geometry", False, f"canonical {canonical} does not satisfy {requirement.geometry}")
        return evidence, MissingReason.NO_LAYER.value
    record_check("geometry", True, f"canonical {canonical} satisfies {requirement.geometry}")

    # 2. fields
    if requirement.required_fields:
        if record.fields is None:
            record_check("fields", False, "fields unknown-deferred")
            return evidence, MissingReason.UNKNOWN_DEFERRED.value
        layer_fields = {f.name: f.type for f in record.fields}
        missing = [f for f in requirement.required_fields if f not in layer_fields]
        if missing:
            record_check("fields", False, f"missing fields: {missing}")
            return evidence, MissingReason.SCHEMA_GAP.value
        type_map = requirement.field_type_map()
        bad_types = [
            f
            for f in requirement.required_fields
            if f in type_map and not _type_compatible(layer_fields[f], type_map[f])
        ]
        if bad_types:
            record_check("fields", False, f"incompatible types: {bad_types}")
            return evidence, MissingReason.SCHEMA_GAP.value
        record_check("fields", True, "required fields present with compatible types")
    else:
        record_check("fields", True, "no attribute constraint")

    # 3. crs
    if requirement.crs_authid is not None:
        if not record.crs_known or not record.crs_authid:
            record_check("crs", False, "layer CRS unknown-deferred")
            return evidence, MissingReason.UNKNOWN_DEFERRED.value
        if record.crs_authid != requirement.crs_authid:
            record_check("crs", False, f"layer {record.crs_authid} != required {requirement.crs_authid}")
            return evidence, MissingReason.CRS_GAP.value
        record_check("crs", True, f"CRS {record.crs_authid} matches")
    else:
        record_check("crs", True, "no CRS constraint")

    # 4. reachability
    if record.reachable == Reachability.KNOWN_UNREACHABLE:
        record_check("reachability", False, "known unreachable")
        return evidence, MissingReason.INVALID_CANDIDATE.value
    record_check("reachability", True, f"reachable state {record.reachable.value}")

    # 5. coverage (ESTIMATE pre-checks only)
    if requirement.extent is not None:
        if record.extent is None:
            record_check("coverage", False, "extent unknown-deferred")
            return evidence, MissingReason.UNKNOWN_DEFERRED.value
        contained = _bbox_contains_native(record.extent, requirement.extent)
        if contained is None:
            record_check("coverage", False, "cross-CRS extent unknown-deferred")
            return evidence, MissingReason.UNKNOWN_DEFERRED.value
        if not contained:
            # No area ratios are computed QGIS-free (naive degrees²-vs-m²
            # forbidden): full containment is the only ESTIMATE pass.
            # With threshold < 1.0 a partial overlap might still satisfy,
            # but that ratio is normative QGIS work → unknown-deferred.
            if requirement.coverage_threshold < 1.0:
                record_check("coverage", False, "partial overlap with threshold<1.0 unknown-deferred")
                return evidence, MissingReason.UNKNOWN_DEFERRED.value
            record_check("coverage", False, "layer bbox does not contain requirement bbox (ESTIMATE)")
            return evidence, MissingReason.COVERAGE_GAP.value
        record_check("coverage", True, "layer bbox contains requirement bbox (ESTIMATE)")
    else:
        record_check("coverage", True, "no coverage constraint")

    # 6. validity (layer-opened only; per-feature validity is validation scope)
    if not record.valid:
        record_check("validity", False, "layer not valid")
        return evidence, MissingReason.INVALID_CANDIDATE.value
    if record.feature_count_state == ValueState.KNOWN and record.feature_count == 0:
        record_check("validity", False, "layer empty (0 features known)")
        return evidence, MissingReason.INVALID_CANDIDATE.value
    record_check("validity", True, "layer valid (opened; per-feature validity deferred to validation)")

    # 7. temporal (trailing; has_time None on either side constrains nothing)
    if requirement.has_time is not None:
        if record.has_time is None:
            record_check("temporal", False, "temporal support unknown-deferred")
            return evidence, MissingReason.UNKNOWN_DEFERRED.value
        if record.has_time != requirement.has_time:
            record_check("temporal", False, f"layer has_time={record.has_time} != required {requirement.has_time}")
            return evidence, MissingReason.NO_LAYER.value
        record_check("temporal", True, f"has_time={record.has_time} matches")
    else:
        record_check("temporal", True, "no temporal constraint")

    return evidence, None


def _make_step(
    op: str,
    input_refs: Sequence[str],
    params: dict[str, Any],
    provisional_reasons: Sequence[str],
    output_ref: str,
) -> TransformationStep:
    """Build a declared step with sorted params (deterministic)."""
    return TransformationStep(
        op=op,
        step_schema_version=STEP_SCHEMA_VERSION,
        executor="qgis-processing",
        executor_alg_ref=None,  # resolved at data.run_transformation, never here
        params=tuple(sorted(params.items())),
        input_refs=tuple(input_refs),
        output_ref=output_ref,
        provisional=True,
        provisional_reasons=tuple(provisional_reasons),
    )


def _member_ok(
    requirement: DataRequirement, record: LayerRecord, *, require_crs_match: bool, require_geometry_match: bool = True
) -> bool:
    """Shared input-hygiene gate for single-step chain members.

    A member must satisfy every AVAILABLE precondition the emitted op does
    not itself repair: validity, reachability, non-emptiness, geometry
    (unless the op is a conversion whose source family is checked by the
    branch), and (when required) CRS equality + ESTIMATE coverage. Gaps
    the op cannot close in one step disqualify the member (multi-step
    chains are an M4-T03+ seam).
    """
    if not record.valid or record.reachable == Reachability.KNOWN_UNREACHABLE:
        return False
    if record.feature_count_state == ValueState.KNOWN and record.feature_count == 0:
        return False
    if require_geometry_match and not geometry_satisfies(
        requirement.geometry, canonicalize_geometry(record.geometry_type)
    ):
        return False
    if requirement.has_time is not None:
        if record.has_time is None or record.has_time != requirement.has_time:
            return False
    if require_crs_match and requirement.crs_authid is not None:
        if not record.crs_known or not record.crs_authid:
            return False
        if record.crs_authid != requirement.crs_authid:
            return False
    return _coverage_estimate_ok(requirement, record)


def _single_step_chains(
    requirement: DataRequirement, inventory: LayerInventory
) -> list[tuple[TransformationStep, ...]]:
    """Enumerate single-step DERIVABLE chains in §8 op order, layer_id order.

    Only EMIT_OPS are generated (clip/filter accepted in schemas but never
    emitted by v1 enumeration). Every emitted chain is provisional: method
    params and executor pins resolve at validation/execution.
    """
    chains: list[tuple[TransformationStep, ...]] = []
    allowed = set(requirement.transformations_allowed)
    records = {r.layer_id: r for r in inventory.records}

    def fields_of(record: LayerRecord) -> dict[str, str] | None:
        if record.fields is None:
            return None
        return {f.name: f.type for f in record.fields}

    for record in inventory.records:
        canonical = canonicalize_geometry(record.geometry_type)

        # reproject-vector: everything matches except CRS (both defined).
        # Vector-only: rasters warp via reproject-raster (resampling).
        if "reproject-vector" in allowed and "reproject-vector" in EMIT_OPS:
            if (
                canonical != "Raster"
                and _member_ok(requirement, record, require_crs_match=False)
                and requirement.crs_authid is not None
                and record.crs_known
                and record.crs_authid
                and record.crs_authid != requirement.crs_authid
                and _fields_ok(requirement, fields_of(record))
            ):
                chains.append(
                    (
                        _make_step(
                            "reproject-vector",
                            [record.layer_id],
                            {"target_crs": requirement.crs_authid},
                            ["crs-transform unverified", "executor-alg-unpinned"],
                            f"derived:reproject-vector:{record.layer_id}",
                        ),
                    )
                )

        # reproject-raster: CRS mismatch where a raster is involved AND
        # geometry/coverage already satisfied (reprojection never converts
        # geometry families — conversion cases must not emit this op).
        if "reproject-raster" in allowed and "reproject-raster" in EMIT_OPS:
            raster_involved = canonical == "Raster" or requirement.geometry == "Raster"
            if (
                raster_involved
                and _member_ok(requirement, record, require_crs_match=False)
                and geometry_satisfies(requirement.geometry, canonical)
                and requirement.crs_authid is not None
                and record.crs_known
                and record.crs_authid
                and record.crs_authid != requirement.crs_authid
                and _fields_ok(requirement, fields_of(record))
            ):
                chains.append(
                    (
                        _make_step(
                            "reproject-raster",
                            [record.layer_id],
                            {"target_crs": requirement.crs_authid},
                            [
                                "resampling-method-undecided",
                                "datum-shift-uncertainty",
                                "executor-alg-unpinned",
                            ],
                            f"derived:reproject-raster:{record.layer_id}",
                        ),
                    )
                )

        # raster-to-vector / vector-to-raster conversions (provisional:
        # method params resolve at validation/execution).
        if "raster-to-vector" in allowed and "raster-to-vector" in EMIT_OPS:
            if canonical == "Raster" and requirement.geometry in (
                "Point",
                "LineString",
                "Polygon",
                "Table",
            ):
                if _member_ok(requirement, record, require_crs_match=True, require_geometry_match=False) and _fields_ok(
                    requirement, fields_of(record)
                ):
                    chains.append(
                        (
                            _make_step(
                                "raster-to-vector",
                                [record.layer_id],
                                {"method": "deferred-to-validation"},
                                ["conversion-method-undecided", "executor-alg-unpinned"],
                                f"derived:raster-to-vector:{record.layer_id}",
                            ),
                        )
                    )
        if "vector-to-raster" in allowed and "vector-to-raster" in EMIT_OPS:
            if requirement.geometry == "Raster" and canonical in (
                "Point",
                "LineString",
                "Polygon",
            ):
                if _member_ok(requirement, record, require_crs_match=True, require_geometry_match=False) and _fields_ok(
                    requirement, fields_of(record)
                ):
                    chains.append(
                        (
                            _make_step(
                                "vector-to-raster",
                                [record.layer_id],
                                {"method": "deferred-to-validation"},
                                ["conversion-method-undecided", "executor-alg-unpinned"],
                                f"derived:vector-to-raster:{record.layer_id}",
                            ),
                        )
                    )

    # join: ordered layer pairs covering the field union; deterministic key
    # choice = first common coercible field in sorted order (frozen rule).
    if "join" in allowed and "join" in EMIT_OPS and requirement.required_fields:
        ids = [r.layer_id for r in inventory.records]
        for i, left_id in enumerate(ids):
            for right_id in ids[i + 1 :]:
                left = records[left_id]
                right = records[right_id]
                # Both members must satisfy every precondition the single
                # join step does not repair (geometry/CRS/coverage/validity).
                if not _member_ok(requirement, left, require_crs_match=True):
                    continue
                if not _member_ok(requirement, right, require_crs_match=True):
                    continue
                left_fields = fields_of(left)
                right_fields = fields_of(right)
                if left_fields is None or right_fields is None:
                    continue
                union = set(left_fields) | set(right_fields)
                if not set(requirement.required_fields) <= union:
                    continue
                common = sorted(set(left_fields) & set(right_fields))
                keys = [
                    k
                    for k in common
                    if (normalize_field_type(left_fields[k]), normalize_field_type(right_fields[k])) in COERCIBLE
                    or (normalize_field_type(right_fields[k]), normalize_field_type(left_fields[k])) in COERCIBLE
                ]
                if not keys:
                    continue
                key = keys[0]
                chains.append(
                    (
                        _make_step(
                            "join",
                            [left_id, right_id],
                            {"key": key, "cardinality": "1:1-proposed"},
                            [
                                "cardinality-unconfirmed",
                                "null-duplicate-keys-unchecked",
                                "executor-alg-unpinned",
                            ],
                            f"derived:join:{left_id}+{right_id}",
                        ),
                    )
                )

    return chains


def _fields_ok(requirement: DataRequirement, layer_fields: dict[str, str] | None) -> bool:
    """Field subset + coercion pre-check shared by chain preconditions."""
    if not requirement.required_fields:
        return True
    if layer_fields is None:
        return False
    type_map = requirement.field_type_map()
    for name in requirement.required_fields:
        if name not in layer_fields:
            return False
        if name in type_map and not _type_compatible(layer_fields[name], type_map[name]):
            return False
    return True


def _coverage_estimate_ok(requirement: DataRequirement, record: LayerRecord) -> bool:
    """ESTIMATE coverage pre-check for chain preconditions (same-CRS bbox only)."""
    if requirement.extent is None:
        return True
    if record.extent is None:
        return False
    return _bbox_contains_native(record.extent, requirement.extent) is True


def classify_requirement(
    requirement: DataRequirement,
    inventory: LayerInventory,
    max_chain_steps: int = MAX_CHAIN_STEPS,
) -> ClassificationResult:
    """Deterministic AVAILABLE / DERIVABLE / MISSING classification (§3).

    QGIS-free predicate over (requirement, inventory snapshot). No LLM, no
    network, no timestamps in the verdict. UNKNOWN states never satisfy a
    check. Returns AVAILABLE on the first fully-passing layer (inventory
    order), else the shortest deterministic DERIVABLE chain (op order,
    then layer_id order), else MISSING with the best-candidate reason.
    v1 enumerates single-step chains only (see _single_step_chains).
    """
    # v1 fulfills only the local-project path (snapshot layers).
    # local-file and provider:<id> sources are future fulfillment paths
    # (register_local_file / adapters, M4-T03+): accepted in the contract
    # but not evaluated here.
    if "local-project" not in requirement.acceptable_sources:
        return ClassificationResult(
            state=AvailabilityState.MISSING,
            requirement_name=requirement.name,
            layer_id=None,
            evidence=(),
            missing_reason=MissingReason.NO_LAYER,
            chain=(),
            provisional=False,
            provisional_reasons=(),
            snapshot_id=inventory.snapshot_id,
            snapshot_truncated=inventory.truncated,
        )
    evidence: list[CheckEvidence] = []
    best_reason: str | None = None
    best_layer: str | None = None
    best_passes = -1

    for record in inventory.records:
        layer_evidence, failure = _check_layer(requirement, record)
        evidence.extend(layer_evidence)
        if failure is None:
            return ClassificationResult(
                state=AvailabilityState.AVAILABLE,
                requirement_name=requirement.name,
                layer_id=record.layer_id,
                evidence=tuple(evidence),
                missing_reason=None,
                chain=(),
                provisional=True,
                provisional_reasons=(
                    "validity-is-opened-only",
                    "coverage-is-estimate",
                ),
                snapshot_id=inventory.snapshot_id,
                snapshot_truncated=inventory.truncated,
            )
        # Best candidate = most passed checks; ties → inventory (layer_id) order.
        passes = sum(1 for item in layer_evidence if item.passed)
        if passes > best_passes:
            best_passes = passes
            best_reason = failure
            best_layer = record.layer_id

    if not inventory.records:
        missing = MissingReason.TRUNCATED_INVENTORY if inventory.truncated else MissingReason.NO_LAYER
        return ClassificationResult(
            state=AvailabilityState.MISSING,
            requirement_name=requirement.name,
            layer_id=None,
            evidence=(),
            missing_reason=missing,
            chain=(),
            provisional=False,
            provisional_reasons=(),
            snapshot_id=inventory.snapshot_id,
            snapshot_truncated=inventory.truncated,
        )

    # DERIVABLE: shortest chain first. v1 enumerates single-step chains
    # only; multi-step composition over symbolic derived states is an
    # explicit seam for M4-T03+ (output_refs are symbolic and composable).
    chains = _single_step_chains(requirement, inventory)
    usable = [c for c in chains if len(c) <= max_chain_steps]
    if usable:
        chosen = sorted(
            usable,
            key=lambda c: (
                len(c),
                [TRANSFORM_OPS.index(step.op) for step in c],
                [step.input_refs for step in c],
            ),
        )[0]
        reasons: list[str] = ["chain-unexecuted"]
        for step in chosen:
            reasons.extend(step.provisional_reasons)
        return ClassificationResult(
            state=AvailabilityState.DERIVABLE,
            requirement_name=requirement.name,
            layer_id=chosen[0].input_refs[0] if chosen[0].input_refs else None,
            evidence=tuple(evidence),
            missing_reason=None,
            chain=chosen,
            provisional=True,
            provisional_reasons=tuple(dict.fromkeys(reasons)),
            snapshot_id=inventory.snapshot_id,
            snapshot_truncated=inventory.truncated,
        )
    if chains and not usable:
        return ClassificationResult(
            state=AvailabilityState.MISSING,
            requirement_name=requirement.name,
            layer_id=best_layer,
            evidence=tuple(evidence),
            missing_reason=MissingReason.TRANSFORM_EXCEEDS_BOUNDS,
            chain=(),
            provisional=False,
            provisional_reasons=(),
            snapshot_id=inventory.snapshot_id,
            snapshot_truncated=inventory.truncated,
        )

    # Truncated snapshots can never prove absence.
    if inventory.truncated and (best_reason == MissingReason.NO_LAYER.value or best_layer is None):
        reason = MissingReason.TRUNCATED_INVENTORY
    else:
        reason = MissingReason(best_reason) if best_reason else MissingReason.NO_LAYER
    return ClassificationResult(
        state=AvailabilityState.MISSING,
        requirement_name=requirement.name,
        layer_id=best_layer,
        evidence=tuple(evidence),
        missing_reason=reason,
        chain=(),
        provisional=False,
        provisional_reasons=(),
        snapshot_id=inventory.snapshot_id,
        snapshot_truncated=inventory.truncated,
    )


# ---------------------------------------------------------------------------
# Deterministic serialization helpers
# ---------------------------------------------------------------------------


def _dataclass_to_dict(value: Any) -> Any:
    """Recursively convert frozen dataclasses/enums/tuples to JSON values."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (tuple, list)):
        return [_dataclass_to_dict(v) for v in value]
    if isinstance(value, dict):
        return {k: _dataclass_to_dict(v) for k, v in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        result: dict[str, Any] = {}
        for f in value.__dataclass_fields__:
            item = getattr(value, f)
            if item is None:
                continue  # absence pattern: omit Nones
            result[f] = _dataclass_to_dict(item)
        return result
    return value


def classification_to_dict(result: ClassificationResult) -> dict[str, Any]:
    """ClassificationResult as a plain JSON-compatible dict (Nones omitted)."""
    return dict(_dataclass_to_dict(result))


def classification_canonical_json(result: ClassificationResult) -> str:
    """Deterministic canonical JSON for a verdict (sorted keys)."""
    return json.dumps(
        classification_to_dict(result),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Validation contracts, M4-T03 (QGIS-free shapes; QGIS executes in
# validation_qgis.py). Frozen §7 vocabulary: verdicts are exactly
# VALID | EMPTY | INVALID — PARTIAL is a validity *field*, never a verdict.
# ---------------------------------------------------------------------------

VALIDATION_MODEL_VERSION = "1.0"  # versions ValidationReport shape, not the QGIS executor

# Frozen §7 check order (first failure wins). "snapshot-freshness" is an
# M4-T03 validation precondition (stale snapshot → fail closed), not one of
# §7's eight data checks.
VALIDATION_CHECK_ORDER: tuple[str, ...] = (
    "snapshot-freshness",
    "allowlist",
    "integrity",
    "parseability",
    "emptiness",
    "schema",
    "crs",
    "geometry",
    "coverage",
)


class ValidationVerdict(str, Enum):
    """Validation outcome. No PARTIAL verdict (see validity field)."""

    VALID = "valid"
    EMPTY = "empty"
    INVALID = "invalid"


class SatisfactionState(str, Enum):
    """Requirement-satisfaction outcome derived from one ValidationReport.

    Narrow by design: derived from a single report, carrying no geometry or
    extent math of its own. Classification (AVAILABLE/DERIVABLE/MISSING)
    remains the only availability authority.
    """

    SATISFIED = "satisfied"
    NOT_SATISFIED = "not-satisfied"
    UNKNOWN_DEFERRED = "unknown-deferred"
    PARTIAL = "partial"


@dataclass(frozen=True)
class ValidationCheck:
    """One ordered validation check outcome."""

    name: str  # one of VALIDATION_CHECK_ORDER
    passed: bool
    skipped: bool  # True only for EMPTY short-circuit ("skipped-empty") or deferred
    detail: str


@dataclass(frozen=True)
class ValidationReport:
    """QGIS-authoritative validation result (§7 output shape + linkage)."""

    subject_kind: str  # "layer-ref" | "file"
    subject_ref: str  # layer_id or minimized path (never raw secrets)
    requirement_name: str | None
    snapshot_id: str | None
    verdict: ValidationVerdict
    checks: tuple[ValidationCheck, ...]  # VALIDATION_CHECK_ORDER, first-failure-wins
    crs_authid: str | None
    crs_known: bool
    geometry_canonical: str  # one of CANONICAL_GEOMETRIES
    field_list: tuple[tuple[str, str], ...]  # (name, normalized type) pairs
    extent: LayerExtent | None
    fields_state: ValueState
    feature_count: int | None
    feature_count_state: ValueState
    validity: str  # "FULL" | "PARTIAL" | "UNCHECKED"
    validity_sample: tuple[int, int | None] | None  # (sampled, total|None)
    coverage_met: bool | None  # None = unknown/deferred
    coverage_method: str | None  # e.g. "transformed-bbox-containment"
    has_time: bool | None  # temporal activity if determined, else None
    warnings: tuple[str, ...]
    validation_version: str = VALIDATION_MODEL_VERSION

    def field_map(self) -> dict[str, str]:
        """field_list pairs as a dict."""
        return dict(self.field_list)


@dataclass(frozen=True)
class JoinKeyReport:
    """Join-key validation outcome (§7 check 5 rule)."""

    key: str
    present_both: bool
    coercible: bool
    nulls_found: bool
    duplicates_found: bool
    rows_scanned: int
    complete: bool  # False = capped sample; validation confirms/downgrades
    verdict: ValidationVerdict  # VALID or INVALID (never EMPTY)


@dataclass(frozen=True)
class SatisfactionResult:
    """Requirement-satisfaction derived from one ValidationReport (§6)."""

    state: SatisfactionState
    requirement_name: str
    subject_ref: str
    validation_verdict: ValidationVerdict
    validation_ref: str  # sha256 of the report canonical JSON
    evidence: tuple[str, ...]  # templated "check=pass|fail|skip:detail" lines
    reasons: tuple[str, ...]  # stable reason codes (see satisfy_requirement)
    snapshot_id: str | None


def report_to_dict(report: ValidationReport) -> dict[str, Any]:
    """ValidationReport as a plain JSON-compatible dict (Nones omitted)."""
    return dict(_dataclass_to_dict(report))


def report_canonical_json(report: ValidationReport) -> str:
    """Deterministic canonical JSON for a report (sorted keys)."""
    return json.dumps(
        report_to_dict(report),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def report_identity(report: ValidationReport) -> str:
    """sha256 identity of a report's canonical bytes (validation_ref)."""
    return hashlib.sha256(report_canonical_json(report).encode("utf-8")).hexdigest()


def evaluate_join_values(
    key: str,
    left_fields: dict[str, str],
    right_fields: dict[str, str],
    left_values: Sequence[Any],
    right_values: Sequence[Any],
    complete: bool,
) -> JoinKeyReport:
    """Evaluate join-key validity over detached value lists (pure).

    Feature iteration stays in validation_qgis (main thread); this function
    applies only the frozen rule: key present in both inputs with
    coercion-compatible types (exact + Int→Double, normalized names), no
    nulls, no duplicates on the 1:1-required side. Any violation →
    INVALID with the failing condition; `complete=False` is recorded for
    the caller to treat as provisional.
    """
    if key not in left_fields or key not in right_fields:
        return JoinKeyReport(
            key=key,
            present_both=False,
            coercible=False,
            nulls_found=False,
            duplicates_found=False,
            rows_scanned=len(left_values) + len(right_values),
            complete=complete,
            verdict=ValidationVerdict.INVALID,
        )
    left_type = normalize_field_type(left_fields[key])
    right_type = normalize_field_type(right_fields[key])
    if (left_type, right_type) not in COERCIBLE and (right_type, left_type) not in COERCIBLE:
        return JoinKeyReport(
            key=key,
            present_both=True,
            coercible=False,
            nulls_found=False,
            duplicates_found=False,
            rows_scanned=len(left_values) + len(right_values),
            complete=complete,
            verdict=ValidationVerdict.INVALID,
        )
    nulls = any(v is None for v in list(left_values) + list(right_values))
    if nulls:
        return JoinKeyReport(
            key=key,
            present_both=True,
            coercible=True,
            nulls_found=True,
            duplicates_found=False,
            rows_scanned=len(left_values) + len(right_values),
            complete=complete,
            verdict=ValidationVerdict.INVALID,
        )
    seen_left = set()
    duplicates = False
    for value in left_values:
        token = json.dumps(value, sort_keys=True, default=str)
        if token in seen_left:
            duplicates = True
            break
        seen_left.add(token)
    if not duplicates:
        seen_right = set()
        for value in right_values:
            token = json.dumps(value, sort_keys=True, default=str)
            if token in seen_right or token in seen_left:
                duplicates = True
                break
            seen_right.add(token)
    if duplicates:
        return JoinKeyReport(
            key=key,
            present_both=True,
            coercible=True,
            nulls_found=False,
            duplicates_found=True,
            rows_scanned=len(left_values) + len(right_values),
            complete=complete,
            verdict=ValidationVerdict.INVALID,
        )
    return JoinKeyReport(
        key=key,
        present_both=True,
        coercible=True,
        nulls_found=False,
        duplicates_found=False,
        rows_scanned=len(left_values) + len(right_values),
        complete=complete,
        verdict=ValidationVerdict.VALID,
    )


def satisfy_requirement(requirement: DataRequirement, report: ValidationReport) -> SatisfactionResult:
    """Derive requirement satisfaction from one ValidationReport (pure).

    No GIS math: only closed-enum/field/coercion/verdict mapping over
    QGIS-produced values. Order: INVALID/EMPTY verdicts → deferred-blocking
    unknowns → terminal PARTIAL validity → constraint re-evaluation →
    SATISFIED. Never claims SATISFIED from UNKNOWN states.
    """
    evidence = tuple(
        f"{c.name}={'pass' if c.passed else 'fail'}{':skipped' if c.skipped else ''}:{c.detail}" for c in report.checks
    )
    ref = report_identity(report)

    def decide(
        state: SatisfactionState, reasons: Sequence[str], validation_verdict: ValidationVerdict | None = None
    ) -> SatisfactionResult:
        return SatisfactionResult(
            state=state,
            requirement_name=requirement.name,
            subject_ref=report.subject_ref,
            validation_verdict=validation_verdict or report.verdict,
            validation_ref=ref,
            evidence=evidence,
            reasons=tuple(reasons),
            snapshot_id=report.snapshot_id,
        )

    if report.verdict == ValidationVerdict.INVALID:
        failed = next((c.name for c in report.checks if not c.passed and not c.skipped), "unknown")
        return decide(SatisfactionState.NOT_SATISFIED, (f"invalid:{failed}",))
    if report.verdict == ValidationVerdict.EMPTY:
        return decide(SatisfactionState.NOT_SATISFIED, ("empty-dataset",))

    # Deferred-blocking unknowns: requirement constrains a dimension the
    # report could not determine.
    if requirement.extent is not None and report.extent is None:
        return decide(SatisfactionState.UNKNOWN_DEFERRED, ("deferred:extent",))
    if requirement.crs_authid is not None and not report.crs_known:
        return decide(SatisfactionState.UNKNOWN_DEFERRED, ("deferred:crs",))
    if requirement.required_fields and report.fields_state != ValueState.KNOWN:
        return decide(SatisfactionState.UNKNOWN_DEFERRED, ("deferred:fields",))
    if requirement.extent is not None and report.coverage_met is None:
        return decide(SatisfactionState.UNKNOWN_DEFERRED, ("deferred:coverage",))

    # Terminal PARTIAL validity (known-incomplete, not unknown).
    if report.validity == "PARTIAL":
        return decide(SatisfactionState.PARTIAL, ("partial-validity",))

    # Constraint re-evaluation over authoritative values.
    if not geometry_satisfies(requirement.geometry, report.geometry_canonical):
        return decide(SatisfactionState.NOT_SATISFIED, ("geometry-mismatch",))
    field_map = report.field_map()
    type_map = requirement.field_type_map()
    for name in requirement.required_fields:
        if name not in field_map:
            return decide(SatisfactionState.NOT_SATISFIED, ("schema-gap",))
        if name in type_map and not _type_compatible(field_map[name], type_map[name]):
            return decide(SatisfactionState.NOT_SATISFIED, ("schema-gap",))
    if requirement.crs_authid is not None and report.crs_authid != requirement.crs_authid:
        return decide(SatisfactionState.NOT_SATISFIED, ("crs-mismatch",))
    if requirement.extent is not None and report.coverage_met is False:
        return decide(SatisfactionState.NOT_SATISFIED, ("coverage-gap",))
    if requirement.has_time is not None:
        if report.has_time is None:
            return decide(SatisfactionState.UNKNOWN_DEFERRED, ("deferred:temporal",))
        if report.has_time != requirement.has_time:
            return decide(SatisfactionState.NOT_SATISFIED, ("temporal-mismatch",))
    return decide(SatisfactionState.SATISFIED, ())
