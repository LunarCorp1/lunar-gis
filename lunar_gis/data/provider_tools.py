"""M4-T05 governed provider tools: data.search_catalog + data.download_dataset.

- ``data.search_catalog`` v1 (MEDIUM risk, no confirmation — search is
  read-only and capped; intent-audit still recorded by the executor):
  provider_id + structured query → results.
- ``data.download_dataset`` v1 (HIGH risk, confirmation-gated):
  provider_id + dataset_id + asset_id → sandbox LocalFile + provenance
  record. The engine creates one sandbox per acquisition; tools never
  accept caller-supplied absolute paths.

Search-then-download are separate invocations (no auto-download of
search hits). Handlers resolve adapters lazily via the registry (no
provider import at module import time) and fail closed offline.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from typing import Any

from lunar_gis.agent.registry import (
    ToolRegistry,
    ToolRisk,
    ToolSpec,
    ToolVersion,
)
from lunar_gis.data.adapters.base import SearchQuery

SEARCH_CATALOG_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "provider_id": {"type": "string"},
        "bbox": {"type": "array", "items": {"type": "number"}},
        "datetime_range": {"type": "array", "items": {"type": "string"}},
        "collection": {"type": "string"},
        "limit": {"type": "integer"},
        "tags": {"type": "object"},
        "place": {"type": "string"},
    },
    "required": ["provider_id"],
    "additionalProperties": False,
}

SEARCH_CATALOG_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "results": {"type": "array", "items": {"type": "object"}},
        "total": {"type": "integer"},
        "error": {"type": "string"},
        "provider_id": {"type": "string"},
    },
    "required": ["ok", "provider_id"],
    "additionalProperties": False,
}

DOWNLOAD_DATASET_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "provider_id": {"type": "string"},
        "dataset_id": {"type": "string"},
        "asset_id": {"type": "string"},
        "workspace_dir": {"type": "string"},
    },
    "required": ["provider_id", "dataset_id", "asset_id"],
    "additionalProperties": False,
}

DOWNLOAD_DATASET_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "sandbox_relpath": {"type": "string"},
        "size_bytes": {"type": "integer"},
        "sha256": {"type": "string"},
        "provenance_ref": {"type": "string"},
        "error": {"type": "string"},
        "provider_id": {"type": "string"},
    },
    "required": ["ok", "provider_id"],
    "additionalProperties": False,
}

SEARCH_CATALOG_TOOL_SPEC = ToolSpec(
    name="data.search_catalog",
    version=ToolVersion(major=1, minor=0, patch=0),
    risk=ToolRisk.MEDIUM,
    handler=None,
    input_schema=SEARCH_CATALOG_INPUT_SCHEMA,
    output_schema=SEARCH_CATALOG_OUTPUT_SCHEMA,
    description=(
        "Search a controlled provider catalog with a structured query (read-only, capped). "
        "Flow: geocode place names to a bbox with osm.nominatim first; "
        "Overpass needs bbox+tags; STAC needs bbox/collection."
    ),
)

DOWNLOAD_DATASET_TOOL_SPEC = ToolSpec(
    name="data.download_dataset",
    version=ToolVersion(major=1, minor=0, patch=0),
    risk=ToolRisk.HIGH,
    handler=None,
    input_schema=DOWNLOAD_DATASET_INPUT_SCHEMA,
    output_schema=DOWNLOAD_DATASET_OUTPUT_SCHEMA,
    description="Download one provider asset into a fresh sandbox (HIGH risk: confirmation required).",
)


def _build_query(input_data: dict[str, Any]) -> SearchQuery:
    bbox_raw = input_data.get("bbox")
    bbox = tuple(bbox_raw[:4]) if isinstance(bbox_raw, list) and len(bbox_raw) == 4 else None
    dt_raw = input_data.get("datetime_range")
    dt = tuple(dt_raw[:2]) if isinstance(dt_raw, list) and len(dt_raw) == 2 else None
    tags_raw = input_data.get("tags")
    tags = tuple(sorted((str(k), str(v)) for k, v in tags_raw.items())) if isinstance(tags_raw, dict) else ()
    return SearchQuery(
        bbox=bbox,  # type: ignore[arg-type]
        datetime_range=dt,  # type: ignore[arg-type]
        collection=input_data.get("collection"),
        limit=int(input_data.get("limit", 10)),
        tags=tags,
        place=input_data.get("place"),
    )


def search_catalog_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    """Search a provider catalog. Never raises."""
    from lunar_gis.data.adapters import registry as adapter_registry

    provider_id = input_data.get("provider_id", "")
    try:
        adapter = adapter_registry.get(provider_id)
    except KeyError:
        return {
            "ok": False,
            "provider_id": str(provider_id),
            "error": f"unknown-provider (registered: {', '.join(adapter_registry.ids())})",
        }
    try:
        ok, payload = adapter.search(_build_query(input_data))
    except Exception as exc:
        return {"ok": False, "provider_id": provider_id, "error": f"search-failed: {type(exc).__name__}"}
    if not ok:
        return {
            "ok": ok,
            "provider_id": provider_id,
            "results": [],
            "total": 0,
            "error": payload.get("error", ""),
        }
    results = payload.get("results", [])
    total = payload.get("total", 0)
    hint = ""
    if total == 0:
        hint = (
            "no results: simplify the place name (e.g. 'Lake Malawi' instead of "
            "'Lake Malawi Basin'), adjust bbox/tags, or try another provider "
            "(stac.earth-search / osm.overpass / osm.nominatim)"
        )
    return {
        "ok": ok,
        "provider_id": provider_id,
        "results": results,
        "total": total,
        "error": payload.get("error", ""),
        "hint": hint,
    }


def download_dataset_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    """Download one asset into a fresh sandbox + provenance. Never raises."""
    from lunar_gis.data.adapters import registry as adapter_registry

    provider_id = input_data.get("provider_id", "")
    dataset_id = input_data.get("dataset_id", "")
    asset_id = input_data.get("asset_id", "")
    try:
        adapter = adapter_registry.get(provider_id)
    except KeyError:
        return {
            "ok": False,
            "provider_id": str(provider_id),
            "error": f"unknown-provider (registered: {', '.join(adapter_registry.ids())})",
        }
    workspace = input_data.get("workspace_dir")
    try:
        base = workspace if isinstance(workspace, str) and workspace and os.path.isdir(workspace) else None
        sandbox_dir = tempfile.mkdtemp(prefix="lunar-acquire-", dir=base)
    except OSError as exc:
        return {"ok": False, "provider_id": provider_id, "error": f"sandbox-failed: {exc}"}
    try:
        ok, payload = adapter.download(dataset_id, asset_id, sandbox_dir)
    except Exception as exc:
        return {"ok": False, "provider_id": provider_id, "error": f"download-failed: {type(exc).__name__}"}
    if not ok:
        return {"ok": False, "provider_id": provider_id, "error": payload.get("error", "download-failed")}
    # Post-write verification: "ok" must prove the bytes exist. An
    # adapter claiming success without materializing the file is a
    # defect, not a download — fail closed instead of reporting ok.
    from lunar_gis.data.adapters.transport import _safe_join as _transport_safe_join

    verified_path = _transport_safe_join(sandbox_dir, str(payload.get("sandbox_relpath", "")))
    verified_bytes = 0
    verified_sha = ""
    if verified_path is not None and os.path.isfile(verified_path):
        try:
            with open(verified_path, "rb") as handle:
                digest = hashlib.sha256()
                while True:
                    chunk = handle.read(65536)
                    if not chunk:
                        break
                    verified_bytes += len(chunk)
                    digest.update(chunk)
            verified_sha = digest.hexdigest()
        except OSError:
            verified_bytes = 0
    expected_sha = str(payload.get("sha256_actual", "") or "").lower()
    if verified_path is None or verified_bytes == 0:
        return {"ok": False, "provider_id": provider_id, "error": "download-unverified: no bytes on disk"}
    if expected_sha and verified_sha != expected_sha:
        return {"ok": False, "provider_id": provider_id, "error": "download-unverified: checksum mismatch"}
    provenance_ref = ""
    try:
        from lunar_gis.provenance.records import make_record
        from lunar_gis.provenance.store import ProvenanceStore

        record = make_record(
            subject_kind="file",
            subject_ref=str(payload.get("sandbox_relpath", "")),
            origin_kind="provider",
            license_spdx="NONE-declared",
            retrieved_at=_utc_now(),
            provider_id=provider_id,
            provider_version=adapter.provider_version(),
            dataset_id=dataset_id,
            asset_id=asset_id,
            sha256=verified_sha or None,
            source_url=None,
            tool_invocations=(),
        )
        provenance_ref = ProvenanceStore().append(record)
    except Exception:
        provenance_ref = ""
    return {
        "ok": True,
        "provider_id": provider_id,
        "sandbox_dir": sandbox_dir,
        "sandbox_relpath": payload.get("sandbox_relpath", ""),
        "size_bytes": verified_bytes,
        "sha256": verified_sha,
        "provenance_ref": provenance_ref,
    }


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def register_provider_tools(registry: ToolRegistry) -> None:
    for spec in (SEARCH_CATALOG_TOOL_SPEC, DOWNLOAD_DATASET_TOOL_SPEC):
        handler = search_catalog_handler if spec.name == "data.search_catalog" else download_dataset_handler
        registry.register(
            ToolSpec(
                name=spec.name,
                version=spec.version,
                risk=spec.risk,
                handler=handler,
                input_schema=spec.input_schema,
                output_schema=spec.output_schema,
                description=spec.description,
            )
        )


__all__ = [
    "SEARCH_CATALOG_TOOL_SPEC",
    "DOWNLOAD_DATASET_TOOL_SPEC",
    "search_catalog_handler",
    "download_dataset_handler",
    "register_provider_tools",
]
