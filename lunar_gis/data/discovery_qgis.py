"""M4-T02 QGIS project discovery: deterministic LayerInventory snapshots.

Builds a read-only, bounded snapshot of the current QGIS project following
docs/research/M4-DATA-ENGINE-DESIGN.md §§1-2. The ``project`` argument is
duck-typed (real ``QgsProject`` or offline fakes): this module performs no
``import qgis`` and holds no QGIS objects beyond the call.

Strict boundary (M4-T01 §2.3):
- getters only: mapLayers, id, name, providerType, geometryType,
  featureCount, crs/authid, extent, fields, isValid, source,
  temporalProperties, isDirty
- MUST run on the main/GUI thread (QGIS object lifetime and SIP wrappers
  are not thread-safe); off-thread callers receive detached snapshots only
- MUST NOT mutate the project, add layers, start edits, open files, fetch
  URLs, probe reachability, scan features, or touch the network
- implicit provider I/O from getters on remote layers is tolerated with
  UNKNOWN/UNAVAILABLE fallback, never treated as failure

Public API:
- discover_project(project, taken_at=None, max_layers=...) -> LayerInventory
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from lunar_gis.data.contracts import (
    INVENTORY_TRUNCATION_CAP,
    PROVIDER_STORAGE,
    LayerExtent,
    LayerField,
    LayerInventory,
    LayerRecord,
    Reachability,
    StorageKind,
    ValueState,
    compute_snapshot_id,
    redact_source,
)


def _safe_str(value: Any) -> str | None:
    """Best-effort string coercion for display metadata; None on failure."""
    try:
        text = str(value)
    except Exception:
        return None
    return text


def _read_geometry_type(layer: Any) -> str | None:
    """Opaque geometry repr (never canonicalized here; see contracts)."""
    if not hasattr(layer, "geometryType"):
        return None
    try:
        return _safe_str(layer.geometryType())
    except Exception:
        return None


def _read_feature_count(layer: Any) -> tuple[int | None, ValueState]:
    """Feature count with -1 normalized to UNKNOWN (never 0)."""
    if not hasattr(layer, "featureCount"):
        return None, ValueState.UNAVAILABLE
    try:
        raw = layer.featureCount()
    except Exception:
        return None, ValueState.UNAVAILABLE
    try:
        count = int(raw)
    except (TypeError, ValueError):
        return None, ValueState.UNAVAILABLE
    if count == -1:
        return None, ValueState.UNKNOWN
    if count < -1:
        return None, ValueState.UNAVAILABLE
    return count, ValueState.KNOWN


def _read_crs(layer: Any) -> tuple[str | None, bool]:
    """CRS authid with "" normalized to None (UNAVAILABLE authid-empty)."""
    try:
        crs = layer.crs()
    except Exception:
        return None, False
    try:
        authid = crs.authid()
    except Exception:
        return None, False
    if not authid:
        return None, False
    return str(authid), True


def _read_extent(layer: Any) -> tuple[LayerExtent | None, ValueState, str | None]:
    """Bounding box + its CRS; UNAVAILABLE(deferred|error), never scanned."""
    if not hasattr(layer, "extent"):
        return None, ValueState.UNAVAILABLE, "no-extent-api"
    try:
        box = layer.extent()
        xmin = float(box.xMinimum())
        ymin = float(box.yMinimum())
        xmax = float(box.xMaximum())
        ymax = float(box.yMaximum())
    except Exception:
        return None, ValueState.UNAVAILABLE, "extent-error"
    if not all(math.isfinite(v) for v in (xmin, ymin, xmax, ymax)):
        # e.g. empty memory layers report nan boxes: not a usable extent.
        return None, ValueState.UNAVAILABLE, "extent-invalid"
    crs_authid, crs_known = _read_crs(layer)
    if not crs_known or crs_authid is None:
        return None, ValueState.UNAVAILABLE, "extent-crs-unknown"
    return (
        LayerExtent(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax, crs_authid=crs_authid),
        ValueState.KNOWN,
        None,
    )


def _read_fields(layer: Any) -> tuple[tuple[LayerField, ...] | None, ValueState, str | None]:
    """Attribute schema; UNAVAILABLE for rasters or deferred providers."""
    if not hasattr(layer, "fields"):
        return None, ValueState.UNAVAILABLE, "no-fields-api"
    try:
        fields = layer.fields()
    except Exception:
        return None, ValueState.UNAVAILABLE, "fields-error"
    try:
        names = list(fields.names())
    except Exception:
        return None, ValueState.UNAVAILABLE, "fields-names-error"
    result: list[LayerField] = []
    for name in names:
        try:
            field = fields.field(name)
            type_name = _safe_str(field.typeName()) if field is not None else None
        except Exception:
            type_name = None
        result.append(LayerField(name=str(name), type=type_name or "Unknown"))
    return tuple(result), ValueState.KNOWN, None


def _read_valid(layer: Any) -> bool:
    """Layer-opened validity (NOT per-feature geometry validity)."""
    try:
        return bool(layer.isValid())
    except Exception:
        return False


def _read_source(layer: Any) -> str:
    """Redacted provider connection string (credentials stripped)."""
    if not hasattr(layer, "source"):
        return ""
    try:
        raw = layer.source()
    except Exception:
        return ""
    if not isinstance(raw, str):
        return ""
    return redact_source(raw)


def _read_has_time(layer: Any) -> bool | None:
    """Temporal activity flag only (no temporal modeling in M4)."""
    if not hasattr(layer, "temporalProperties"):
        return None
    try:
        props = layer.temporalProperties()
    except Exception:
        return None
    if props is None:
        return None
    try:
        return bool(props.isActive())
    except Exception:
        return None


def _read_storage(provider: str) -> StorageKind:
    """Provider prefix → storage kind; unknown prefixes → UNKNOWN (never guessed)."""
    kind = PROVIDER_STORAGE.get(provider.strip().lower(), "unknown")
    return StorageKind(kind)


def _read_reachable(valid: bool, storage: StorageKind) -> Reachability:
    """Reachability without probing.

    KNOWN_REACHABLE is never assigned at discovery (post-validation only).
    An invalid remote-service layer is the only KNOWN_UNREACHABLE signal
    available without probing; everything else stays UNKNOWN.
    """
    if not valid and storage == StorageKind.REMOTE_SERVICE:
        return Reachability.KNOWN_UNREACHABLE
    return Reachability.UNKNOWN


def _read_project_dirty(project: Any) -> bool:
    if not hasattr(project, "isDirty"):
        return False
    try:
        return bool(project.isDirty())
    except Exception:
        return False


def _discover_layer(layer: Any) -> LayerRecord:
    """Snapshot one layer with per-getter defensive fallbacks."""
    try:
        layer_id = str(layer.id())
    except Exception:
        layer_id = ""
    try:
        name = str(layer.name())
    except Exception:
        name = ""
    try:
        provider = str(layer.providerType())
    except Exception:
        provider = ""

    geometry_type = _read_geometry_type(layer)
    feature_count, feature_count_state = _read_feature_count(layer)
    crs_authid, crs_known = _read_crs(layer)
    extent, extent_state, extent_reason = _read_extent(layer)
    fields, fields_state, fields_reason = _read_fields(layer)
    valid = _read_valid(layer)
    storage = _read_storage(provider)
    reachable = _read_reachable(valid, storage)

    return LayerRecord(
        layer_id=layer_id,
        name=name,
        provider=provider,
        geometry_type=geometry_type,
        crs_authid=crs_authid,
        crs_known=crs_known,
        feature_count=feature_count,
        feature_count_state=feature_count_state,
        extent=extent,
        extent_state=extent_state,
        extent_unavailable_reason=extent_reason,
        fields=fields,
        fields_state=fields_state,
        fields_unavailable_reason=fields_reason,
        source_redacted=_read_source(layer),
        storage=storage,
        reachable=reachable,
        has_time=_read_has_time(layer),
        valid=valid,
    )


def discover_project(
    project: Any,
    *,
    taken_at: str | None = None,
    max_layers: int = INVENTORY_TRUNCATION_CAP,
) -> LayerInventory:
    """Build a deterministic LayerInventory snapshot of a QGIS project.

    Args:
        project: QgsProject (or duck-typed fake) exposing mapLayers().
        taken_at: ISO-8601 UTC envelope timestamp; defaults to now. Pass an
            explicit value in tests for byte-deterministic snapshots.
        max_layers: truncation cap (impl config, non-normative per §16).

    Layers are ordered by layer_id. Snapshots carry snapshot_id, taken_at,
    project dirty state, total_count, and the truncation flag. Must be
    called on the main thread with a live project.
    """
    try:
        layers_map = project.mapLayers()
    except Exception:
        layers_map = {}
    try:
        items = list(layers_map.values())
    except Exception:
        items = []

    records = [_discover_layer(layer) for layer in items]
    records.sort(key=lambda r: r.layer_id)
    total_count = len(records)
    truncated = total_count > max_layers
    if truncated:
        records = records[:max_layers]

    stamp = taken_at if taken_at is not None else datetime.now(timezone.utc).isoformat()
    layer_ids = [r.layer_id for r in records]
    return LayerInventory(
        records=tuple(records),
        snapshot_id=compute_snapshot_id(layer_ids, stamp),
        taken_at=stamp,
        project_dirty=_read_project_dirty(project),
        total_count=total_count,
        truncated=truncated,
    )


__all__ = ["discover_project"]
