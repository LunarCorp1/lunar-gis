"""M4-T07 governed data tools: describe/check/validate/register/load.

- ``data.describe_project`` v1 (READ): live project → LayerInventory dict.
- ``data.check_requirement`` v1 (READ): requirement + inventory →
  classification verdict + evidence (+ fulfillment plan kind).
- ``data.validate_dataset`` v1 (LOW): subject ref → ValidationReport dict.
- ``data.register_local_file`` v1 (LOW): sandbox relpath + declared
  schema → DataProvenance record (origin local-file).
- ``data.load_into_project`` v1 (HIGH): validated sandbox file →
  project layer (explicit confirmation; project mutation).

Handlers resolve the live project via deferred import (fail-closed
without QGIS) or accept a serialized inventory mapping. No network,
no eval, no subprocess. File subjects are sandbox-scoped.
"""

from __future__ import annotations

import os
from typing import Any

from lunar_gis.agent.registry import (
    ToolRegistry,
    ToolRisk,
    ToolSpec,
    ToolVersion,
)

DESCRIBE_PROJECT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"include_fields": {"type": "boolean"}},
    "additionalProperties": False,
}

CHECK_REQUIREMENT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "requirement": {"type": "object"},
        "inventory": {"type": "object"},
    },
    "required": ["requirement"],
    "additionalProperties": False,
}

VALIDATE_DATASET_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "subject_kind": {"type": "string"},
        "subject_ref": {"type": "string"},
        "requirement": {"type": "object"},
        "workspace_dir": {"type": "string"},
    },
    "required": ["subject_kind", "subject_ref"],
    "additionalProperties": False,
}

REGISTER_LOCAL_FILE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sandbox_relpath": {"type": "string"},
        "workspace_dir": {"type": "string"},
        "license_spdx": {"type": "string"},
        "requirement_ref": {"type": "string"},
    },
    "required": ["sandbox_relpath"],
    "additionalProperties": False,
}

DESCRIBE_PROJECT_TOOL_SPEC = ToolSpec(
    name="data.describe_project",
    version=ToolVersion(major=1, minor=0, patch=0),
    risk=ToolRisk.READ,
    handler=None,
    input_schema=DESCRIBE_PROJECT_INPUT_SCHEMA,
    output_schema={"type": "object"},
    description="Snapshot the live QGIS project into a LayerInventory (read-only).",
)

CHECK_REQUIREMENT_TOOL_SPEC = ToolSpec(
    name="data.check_requirement",
    version=ToolVersion(major=1, minor=0, patch=0),
    risk=ToolRisk.READ,
    handler=None,
    input_schema=CHECK_REQUIREMENT_INPUT_SCHEMA,
    output_schema={"type": "object"},
    description="Classify a DataRequirement against an inventory (AVAILABLE/DERIVABLE/MISSING).",
)

VALIDATE_DATASET_TOOL_SPEC = ToolSpec(
    name="data.validate_dataset",
    version=ToolVersion(major=1, minor=0, patch=0),
    risk=ToolRisk.LOW,
    handler=None,
    input_schema=VALIDATE_DATASET_INPUT_SCHEMA,
    output_schema={"type": "object"},
    description="Validate a project layer or sandbox file (QGIS authority).",
)

REGISTER_LOCAL_FILE_TOOL_SPEC = ToolSpec(
    name="data.register_local_file",
    version=ToolVersion(major=1, minor=0, patch=0),
    risk=ToolRisk.LOW,
    handler=None,
    input_schema=REGISTER_LOCAL_FILE_INPUT_SCHEMA,
    output_schema={"type": "object"},
    description="Register a sandbox file with local-file provenance.",
)

LOAD_INTO_PROJECT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sandbox_dir": {"type": "string"},
        "sandbox_relpath": {"type": "string"},
        "layer_name": {"type": "string"},
    },
    "required": ["sandbox_dir", "sandbox_relpath"],
    "additionalProperties": False,
}

LOAD_INTO_PROJECT_TOOL_SPEC = ToolSpec(
    name="data.load_into_project",
    version=ToolVersion(major=1, minor=0, patch=0),
    risk=ToolRisk.HIGH,
    handler=None,
    input_schema=LOAD_INTO_PROJECT_INPUT_SCHEMA,
    output_schema={"type": "object"},
    description=(
        "Validate a sandbox file and add it to the QGIS project as a layer "
        "(HIGH: project mutation, confirmation required)."
    ),
)


def _resolve_project() -> Any | None:
    try:
        from qgis.core import QgsProject  # type: ignore[import-not-found]

        return QgsProject.instance()
    except ImportError:
        return None


def _inventory_to_dict(inventory: Any) -> dict[str, Any]:
    # Duck-typed (records/snapshot_id/taken_at/...) rather than isinstance:
    # import-guard tests may reload contracts mid-session, and the snapshot
    # shape — not module identity — is the contract.
    if not (hasattr(inventory, "records") and hasattr(inventory, "snapshot_id")):
        return {"ok": False, "error": "no-inventory"}
    records = []
    for record in inventory.records:
        extent = None
        if record.extent is not None:
            extent = {
                "xmin": record.extent.xmin,
                "ymin": record.extent.ymin,
                "xmax": record.extent.xmax,
                "ymax": record.extent.ymax,
                "crs_authid": record.extent.crs_authid,
            }
        fields = None
        if record.fields is not None:
            fields = [{"name": f.name, "type": f.type} for f in record.fields]
        records.append(
            {
                "layer_id": record.layer_id,
                "name": record.name,
                "provider": record.provider,
                "geometry_type": record.geometry_type,
                "crs_authid": record.crs_authid,
                "crs_known": record.crs_known,
                "feature_count": record.feature_count,
                "feature_count_state": record.feature_count_state.value,
                "extent": extent,
                "extent_state": record.extent_state.value,
                "fields": fields,
                "fields_state": record.fields_state.value,
                "storage": record.storage.value,
                "reachable": record.reachable.value,
                "valid": record.valid,
            }
        )
    return {
        "ok": True,
        "snapshot_id": inventory.snapshot_id,
        "taken_at": inventory.taken_at,
        "project_dirty": inventory.project_dirty,
        "total_count": inventory.total_count,
        "truncated": inventory.truncated,
        "records": records,
    }


def describe_project_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    """Snapshot the live project. Never raises."""
    from lunar_gis.data.contracts import LayerInventory
    from lunar_gis.data.discovery_qgis import discover_project

    _ = input_data
    project = _resolve_project()
    if project is None:
        return {"ok": False, "error": "qgis-runtime-unavailable"}
    try:
        inventory: LayerInventory = discover_project(project)
    except Exception as exc:
        return {"ok": False, "error": f"discovery-failed: {type(exc).__name__}"}
    return _inventory_to_dict(inventory)


def check_requirement_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    """Classify a requirement. Never raises."""
    from lunar_gis.data.contracts import LayerInventory, parse_requirement
    from lunar_gis.data.fulfillment import plan_fulfillment

    requirement_data = input_data.get("requirement", {})
    if not isinstance(requirement_data, dict):
        return {"ok": False, "error": "requirement must be an object"}
    try:
        requirement = parse_requirement(requirement_data)
    except Exception as exc:
        return {"ok": False, "error": f"invalid-requirement: {exc}"}
    inventory_data = input_data.get("inventory")
    inventory: LayerInventory | None = None
    if isinstance(inventory_data, dict):
        inventory = _inventory_from_dict(inventory_data)
    if inventory is None:
        project = _resolve_project()
        if project is None:
            return {"ok": False, "error": "no-inventory-and-no-qgis"}
        try:
            from lunar_gis.data.discovery_qgis import discover_project

            inventory = discover_project(project)
        except Exception as exc:
            return {"ok": False, "error": f"discovery-failed: {type(exc).__name__}"}
    try:
        plan = plan_fulfillment(requirement, inventory)
    except Exception as exc:
        return {"ok": False, "error": f"classification-failed: {type(exc).__name__}"}
    return {
        "ok": True,
        "availability": plan.availability.value,
        "fulfillment_kind": plan.kind.value,
        "layer_id": plan.layer_id,
        "chain": list(plan.chain),
        "provider_id": plan.provider_id,
        "missing_reason": plan.missing_reason,
        "evidence": list(plan.evidence),
        "snapshot_id": plan.snapshot_id,
        "warnings": list(plan.warnings),
    }


def _inventory_from_dict(data: dict[str, Any]) -> Any | None:
    """Rebuild a LayerInventory from a describe_project payload (or None)."""
    try:
        from lunar_gis.data.contracts import (
            LayerExtent,
            LayerField,
            LayerInventory,
            LayerRecord,
            Reachability,
            StorageKind,
            ValueState,
        )

        records = []
        for item in data.get("records", []):
            extent_data = item.get("extent")
            extent = (
                LayerExtent(
                    xmin=float(extent_data["xmin"]),
                    ymin=float(extent_data["ymin"]),
                    xmax=float(extent_data["xmax"]),
                    ymax=float(extent_data["ymax"]),
                    crs_authid=str(extent_data["crs_authid"]),
                )
                if isinstance(extent_data, dict)
                else None
            )
            fields_data = item.get("fields")
            fields = (
                tuple(LayerField(name=str(f["name"]), type=str(f["type"])) for f in fields_data)
                if isinstance(fields_data, list)
                else None
            )
            records.append(
                LayerRecord(
                    layer_id=str(item["layer_id"]),
                    name=str(item.get("name", "")),
                    provider=str(item.get("provider", "")),
                    geometry_type=item.get("geometry_type"),
                    crs_authid=item.get("crs_authid"),
                    crs_known=bool(item.get("crs_known", False)),
                    feature_count=item.get("feature_count"),
                    feature_count_state=ValueState(item.get("feature_count_state", "unknown")),
                    extent=extent,
                    extent_state=ValueState(item.get("extent_state", "unknown")),
                    fields=fields,
                    fields_state=ValueState(item.get("fields_state", "unknown")),
                    storage=StorageKind(item.get("storage", "unknown")),
                    reachable=Reachability(item.get("reachable", "unknown")),
                    has_time=None,
                    valid=bool(item.get("valid", False)),
                )
            )
        return LayerInventory(
            records=tuple(records),
            snapshot_id=str(data.get("snapshot_id", "")),
            taken_at=str(data.get("taken_at", "")),
            project_dirty=bool(data.get("project_dirty", False)),
            total_count=int(data.get("total_count", len(records))),
            truncated=bool(data.get("truncated", False)),
        )
    except Exception:
        return None


def validate_dataset_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    """Validate a layer or sandbox file. Never raises."""
    from lunar_gis.data.contracts import parse_requirement, report_to_dict

    subject_kind = input_data.get("subject_kind", "")
    subject_ref = input_data.get("subject_ref", "")
    requirement = None
    requirement_data = input_data.get("requirement")
    if isinstance(requirement_data, dict):
        try:
            requirement = parse_requirement(requirement_data)
        except Exception as exc:
            return {"ok": False, "error": f"invalid-requirement: {exc}"}
    try:
        if subject_kind == "layer-ref":
            from lunar_gis.data.validation_qgis import validate_project_layer

            project = _resolve_project()
            if project is None:
                return {"ok": False, "error": "qgis-runtime-unavailable"}
            layer = _find_layer(project, subject_ref)
            if layer is None:
                return {"ok": False, "error": "layer-not-found"}
            record = _record_for(project, layer)
            report = validate_project_layer(record, layer, requirement=requirement)
        elif subject_kind == "file":
            from lunar_gis.data.validation_qgis import validate_local_file

            workspace = input_data.get("workspace_dir")
            sandbox = workspace if isinstance(workspace, str) and workspace and os.path.isdir(workspace) else None
            report = validate_local_file(subject_ref, requirement=requirement, sandbox_root=sandbox)
        else:
            return {"ok": False, "error": "subject_kind must be layer-ref|file"}
    except Exception as exc:
        return {"ok": False, "error": f"validation-failed: {type(exc).__name__}"}
    payload = report_to_dict(report)
    payload["ok"] = True
    return payload


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


def _record_for(project: Any, layer: Any) -> Any:
    from lunar_gis.data.discovery_qgis import discover_project

    inventory = discover_project(project)
    for record in inventory.records:
        if record.layer_id == _layer_id_or_none(layer):
            return record
    raise LookupError("layer not in discovery snapshot")


def register_local_file_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    """Register a sandbox file. Never raises."""
    from lunar_gis.provenance.records import make_record
    from lunar_gis.provenance.store import ProvenanceStore

    relpath = input_data.get("sandbox_relpath", "")
    workspace = input_data.get("workspace_dir")
    if not isinstance(relpath, str) or not relpath:
        return {"ok": False, "error": "sandbox_relpath required"}
    if workspace is not None and (not isinstance(workspace, str) or not os.path.isdir(workspace)):
        return {"ok": False, "error": "workspace_dir is not a directory"}
    normalized = relpath.replace("\\", "/").lstrip("/")
    if normalized.startswith("~") or ":" in normalized or ".." in normalized.split("/"):
        return {"ok": False, "error": "path escapes sandbox"}
    if workspace is not None:
        candidate = os.path.realpath(os.path.join(workspace, *normalized.split("/")))
        root = os.path.realpath(workspace)
        if candidate != root and not candidate.startswith(root + os.sep):
            return {"ok": False, "error": "path escapes sandbox"}
        if not os.path.isfile(candidate):
            return {"ok": False, "error": "not a file"}
    try:
        record = make_record(
            subject_kind="file",
            subject_ref=normalized,
            origin_kind="local-file",
            license_spdx=input_data.get("license_spdx", "NONE-declared") or "NONE-declared",
            retrieved_at=_utc_now(),
            requirement_ref=input_data.get("requirement_ref"),
        )
        ref = ProvenanceStore().append(record)
    except Exception as exc:
        return {"ok": False, "error": f"registration-failed: {type(exc).__name__}"}
    return {"ok": True, "provenance_ref": ref, "sandbox_relpath": normalized}


def load_into_project_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    """Validate a sandbox file and add it to the project. Never raises.

    Sandbox-scoped open (safe-join), suffix+magic gate, probe validity
    check — then and only then ``addMapLayer``. Without QGIS, or for
    invalid files, fails closed without touching the project.
    """
    from lunar_gis.data.adapters.transport import _safe_join as _transport_safe_join
    from lunar_gis.data.validation_qgis import check_magic, check_suffix

    sandbox_dir = input_data.get("sandbox_dir", "")
    relpath = input_data.get("sandbox_relpath", "")
    if not isinstance(sandbox_dir, str) or not sandbox_dir or not os.path.isdir(sandbox_dir):
        return {"ok": False, "error": "sandbox_dir is not a directory"}
    target = _transport_safe_join(sandbox_dir, relpath) if isinstance(relpath, str) else None
    if target is None or not os.path.isfile(target):
        return {"ok": False, "error": "path escapes sandbox or not a file"}
    ok_suffix, suffix_detail = check_suffix(target)
    if not ok_suffix:
        return {"ok": False, "error": f"suffix-rejected: {suffix_detail}"}
    ok_magic, magic_detail = check_magic(target)
    if not ok_magic:
        return {"ok": False, "error": f"magic-rejected: {magic_detail}"}
    project = _resolve_project()
    if project is None:
        return {"ok": False, "error": "qgis-runtime-unavailable"}
    try:
        from qgis.core import QgsRasterLayer, QgsVectorLayer  # type: ignore[import-not-found]
    except ImportError:
        return {"ok": False, "error": "qgis-runtime-unavailable"}
    layer_name = input_data.get("layer_name", "") or os.path.splitext(os.path.basename(target))[0]
    lower = target.lower()
    try:
        if lower.endswith((".tif", ".tiff", ".vrt")):
            probe = QgsRasterLayer(target, layer_name, "gdal")
        else:
            probe = QgsVectorLayer(target, layer_name, "ogr")
        valid = bool(probe.isValid())
    except Exception:
        return {"ok": False, "error": "probe-failed"}
    if not valid:
        return {"ok": False, "error": "layer-invalid: QGIS could not open the file"}
    try:
        project.addMapLayer(probe)
        layer_id = probe.id()
    except Exception:
        return {"ok": False, "error": "add-to-project-failed"}
    return {"ok": True, "layer_id": layer_id, "layer_name": layer_name, "source": target}


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def register_data_tools(registry: ToolRegistry) -> None:
    handlers = {
        "data.describe_project": describe_project_handler,
        "data.check_requirement": check_requirement_handler,
        "data.validate_dataset": validate_dataset_handler,
        "data.register_local_file": register_local_file_handler,
        "data.load_into_project": load_into_project_handler,
    }
    specs = (
        DESCRIBE_PROJECT_TOOL_SPEC,
        CHECK_REQUIREMENT_TOOL_SPEC,
        VALIDATE_DATASET_TOOL_SPEC,
        REGISTER_LOCAL_FILE_TOOL_SPEC,
        LOAD_INTO_PROJECT_TOOL_SPEC,
    )
    for spec in specs:
        registry.register(
            ToolSpec(
                name=spec.name,
                version=spec.version,
                risk=spec.risk,
                handler=handlers[spec.name],
                input_schema=spec.input_schema,
                output_schema=spec.output_schema,
                description=spec.description,
            )
        )


__all__ = [
    "describe_project_handler",
    "check_requirement_handler",
    "validate_dataset_handler",
    "register_local_file_handler",
    "register_data_tools",
]
