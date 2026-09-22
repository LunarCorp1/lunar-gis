"""M4-T05 OSM adapters: bounded Overpass + policy-compliant Nominatim.

Overpass (02Agent/QuickOSM pattern): fixed hosts, area caps, QL
constructed from validated enums by the adapter — never raw Overpass
QL from untrusted input. Tag keys come from a frozen allowlist; values
are escaped. Results merge deterministically.

Nominatim (usage-policy compliance): single ``place`` string only,
URL-encoded + length/charset capped (see base.validate_search_query),
1 req/s + cache honored, attribution mandatory. Usage-policy violation
is a misuse risk — the adapter enforces rate + cache structurally.

Both adapters treat responses as untrusted metadata (T3) and route all
egress through the §5.2/§9 transport validator.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from typing import Any

from lunar_gis.data.adapters.base import (
    ProviderError,
    ProviderLimits,
    SearchQuery,
    error_result,
    ok_result,
    validate_search_query,
)
from lunar_gis.data.adapters.transport import fetch_url

OVERPASS_HOSTS: tuple[str, ...] = (
    "overpass-api.de",
    "overpass.kumi.systems",
)
NOMINATIM_HOST = "nominatim.openstreetmap.org"
PROVIDER_VERSION = "1.0.0"

# Frozen allowlisted OSM tag keys (QuickOSM-style bounded fetch).
ALLOWLISTED_TAG_KEYS: frozenset[str] = frozenset(
    {
        "amenity",
        "building",
        "highway",
        "landuse",
        "leisure",
        "natural",
        "shop",
        "tourism",
        "waterway",
        "healthcare",
        "education",
        "office",
    }
)

# Geometry element → Overpass QL object type (validated enums only).
ELEMENT_TYPES: frozenset[str] = frozenset({"node", "way", "relation"})

# Conservative area cap for a single Overpass request (deg², impl config).
MAX_BBOX_DEG2 = 1.0


def _escape_tag_value(value: str) -> str:
    """Escape an OSM tag value for QL string context."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_overpass_ql(
    bbox: tuple[float, float, float, float],
    tags: tuple[tuple[str, str], ...],
    elements: tuple[str, ...] = ("node", "way"),
) -> tuple[bool, str]:
    """Construct Overpass QL from validated enums. (ok, ql|error)."""
    xmin, ymin, xmax, ymax = bbox
    if not (xmin < xmax and ymin < ymax):
        return False, "invalid bbox"
    if (xmax - xmin) * (ymax - ymin) > MAX_BBOX_DEG2:
        return False, "bbox exceeds area cap"
    for element in elements:
        if element not in ELEMENT_TYPES:
            return False, f"bad element: {element}"
    if not tags:
        return False, "at least one tag required"
    for key, value in tags:
        if key not in ALLOWLISTED_TAG_KEYS:
            return False, f"tag key not allowlisted: {key}"
        if len(value) > 100:
            return False, "tag value exceeds 100 chars"
    bbox_s = f"{ymin},{xmin},{ymax},{xmax}"
    clauses: list[str] = []
    for element in elements:
        for key, value in tags:
            clauses.append(f'{element}["{key}"="{_escape_tag_value(value)}"]({bbox_s});')
    # out geom: ways carry inline member geometry (no separate node fetch
    # needed); nodes arrive as usual. Keeps responses small and parsing
    # single-pass.
    return True, "[out:json][timeout:25];(" + "".join(clauses) + ");out geom;"


def encode_overpass_dataset_id(tags: tuple[tuple[str, str], ...], bbox: tuple[float, float, float, float]) -> str:
    """Encode the recorded search query as a dataset id (re-fetch seam).

    The download path re-validates every piece (tag allowlist, value
    length, bbox finiteness + area cap) — a tampered id fails closed.
    """
    tag_part = ";".join(f"{key}={value}" for key, value in tags)
    x0, y0, x1, y1 = bbox
    return f"osm:tags={tag_part}&bbox={x0},{y0},{x1},{y1}"


def decode_overpass_dataset_id(
    dataset_id: str,
) -> tuple[tuple[tuple[str, str], ...], tuple[float, float, float, float]] | None:
    """Strictly parse an encoded dataset id (None = rejected)."""
    if not isinstance(dataset_id, str) or not dataset_id.startswith("osm:tags="):
        return None
    rest = dataset_id[len("osm:tags=") :]
    if "&bbox=" not in rest:
        return None
    tag_part, _, bbox_part = rest.partition("&bbox=")
    tags: list[tuple[str, str]] = []
    for piece in tag_part.split(";"):
        if "=" not in piece:
            return None
        key, _, value = piece.partition("=")
        if key not in ALLOWLISTED_TAG_KEYS or not value or len(value) > 100:
            return None
        tags.append((key, value))
    if not tags:
        return None
    try:
        coords = [float(v) for v in bbox_part.split(",")]
    except ValueError:
        return None
    if len(coords) != 4 or not all(v == v and abs(v) != float("inf") for v in coords):
        return None
    xmin, ymin, xmax, ymax = coords
    if not (xmin < xmax and ymin < ymax):
        return None
    return tuple(tags), (xmin, ymin, xmax, ymax)


def overpass_json_to_geojson(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """Convert Overpass JSON to (GeoJSON, counts).

    Nodes→Points, ways→LineStrings: pure coordinate restructuring (no
    GIS math). Relations are skipped (boundary resolution out of scope);
    counts report them honestly. The file stays strict GeoJSON (no
    foreign members — OGR warns on those); counts travel in the result
    payload instead.
    """
    elements = payload.get("elements", []) if isinstance(payload, dict) else []
    nodes: dict[int, tuple[float, float]] = {}
    for element in elements:
        if isinstance(element, dict) and element.get("type") == "node":
            try:
                nodes[int(element["id"])] = (float(element["lon"]), float(element["lat"]))
            except (KeyError, TypeError, ValueError):
                continue
    features: list[dict[str, Any]] = []
    skipped_relations = 0
    for element in elements:
        if not isinstance(element, dict):
            continue
        kind = element.get("type")
        tags = element.get("tags", {}) if isinstance(element.get("tags"), dict) else {}
        props = {str(k): str(v) for k, v in tags.items()}
        try:
            eid = int(element["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if kind == "node":
            coords = nodes.get(eid)
            if coords is None:
                continue
            # No string "id" member: OGR warns on non-numeric ids; OSM
            # identity travels in properties instead.
            node_props = {"osm_type": "node", "osm_id": eid, **props}
            features.append(
                {
                    "type": "Feature",
                    "properties": node_props,
                    "geometry": {"type": "Point", "coordinates": list(coords)},
                }
            )
        elif kind == "way":
            line: list[list[float]] = []
            geometry = element.get("geometry", [])
            if isinstance(geometry, list) and geometry:
                for point in geometry:
                    if not isinstance(point, dict):
                        continue
                    try:
                        line.append([float(point["lon"]), float(point["lat"])])
                    except (KeyError, TypeError, ValueError):
                        continue
            else:
                refs = element.get("nodes", [])
                line = [list(nodes[r]) for r in refs if isinstance(r, int) and r in nodes]
            if len(line) < 2:
                continue
            way_props = {"osm_type": "way", "osm_id": eid, **props}
            features.append(
                {
                    "type": "Feature",
                    "properties": way_props,
                    "geometry": {"type": "LineString", "coordinates": line},
                }
            )
        elif kind == "relation":
            skipped_relations += 1
    geojson = {"type": "FeatureCollection", "features": features}
    return geojson, {"features": len(features), "skipped_relations": skipped_relations}


def _write_sandbox_bytes(body: bytes, sandbox_dir: str, relpath: str, max_bytes: int) -> tuple[bool, dict[str, Any]]:
    """Write validated bytes sandbox-scoped (safe-join + byte cap)."""
    import hashlib
    import os

    from lunar_gis.data.adapters.transport import _safe_join as _transport_safe_join

    if len(body) > max_bytes:
        return error_result(ProviderError.QUOTA_EXCEEDED, "payload exceeds max_bytes")
    target = _transport_safe_join(sandbox_dir, relpath)
    if target is None:
        return error_result(ProviderError.INVALID_QUERY, "path escapes sandbox")
    try:
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(body)
    except OSError as exc:
        return error_result(ProviderError.PROVIDER_OFFLINE, f"write-failed: {exc}")
    return True, {
        "sandbox_relpath": relpath,
        "size_bytes": len(body),
        "sha256_actual": hashlib.sha256(body).hexdigest(),
    }


class OverpassAdapter:
    """Bounded Overpass fetch behind the frozen adapter surface."""

    """Bounded Overpass fetch behind the frozen adapter surface."""

    def __init__(self, host: str = OVERPASS_HOSTS[0]) -> None:
        if host not in OVERPASS_HOSTS:
            raise ValueError("Overpass host outside the adapter allowlist")
        self._host = host

    def provider_id(self) -> str:
        return "osm.overpass"

    def provider_version(self) -> str:
        return PROVIDER_VERSION

    def host_allowlist(self) -> tuple[str, ...]:
        return OVERPASS_HOSTS

    def limits(self) -> ProviderLimits:
        return ProviderLimits(
            max_area_km2=100.0,
            max_bytes=50 * 1024 * 1024,
            max_assets=5,
            max_results=50,
            timeout_s=30.0,
            retries=2,
            cache_ttl_s=3600,
        )

    def _query_url(self, ql: str) -> str:
        return f"https://{self._host}/api/interpreter?data={urllib.parse.quote(ql)}"

    def search(self, query: SearchQuery, page_token: str | None = None) -> tuple[bool, dict[str, Any]]:
        _ = page_token
        errors = validate_search_query(query, self.limits())
        if errors:
            return error_result(ProviderError.INVALID_QUERY, "; ".join(errors))
        if query.bbox is None:
            return error_result(ProviderError.INVALID_QUERY, "bbox required for overpass")
        if not query.tags:
            return error_result(ProviderError.INVALID_QUERY, "tags required for overpass")
        ok, ql = build_overpass_ql(query.bbox, query.tags)
        if not ok:
            return error_result(ProviderError.INVALID_QUERY, ql)
        url = self._query_url(ql)
        result = fetch_url(
            url, self.host_allowlist(), timeout_s=self.limits().timeout_s, max_bytes=self.limits().max_bytes
        )
        if not result.ok:
            return error_result(ProviderError.PROVIDER_OFFLINE, result.error or "")
        try:
            payload = json.loads(result.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return error_result(ProviderError.PROVIDER_OFFLINE, "invalid-json")
        elements = payload.get("elements", []) if isinstance(payload, dict) else []
        if not isinstance(elements, list):
            return error_result(ProviderError.PROVIDER_OFFLINE, "malformed-response")
        results = [
            {
                "dataset_id": encode_overpass_dataset_id(query.tags, query.bbox),
                "title": f"OSM {query.tags[0][0]}={query.tags[0][1]} in bbox",
                "provider_id": self.provider_id(),
                "bbox": list(query.bbox),
                "license_spdx": "ODbL-1.0",
                "element_count": len(elements),
            }
        ]
        return ok_result({"results": results, "total": 1})

    def get_metadata(self, dataset_id: str) -> tuple[bool, dict[str, Any]]:
        decoded = decode_overpass_dataset_id(dataset_id)
        if decoded is None:
            # Legacy search ids (osm:k=v) describe the query loosely; only
            # the encoded form carries the re-fetchable query.
            if not dataset_id.startswith("osm:"):
                return error_result(ProviderError.INVALID_QUERY, "bad dataset_id")
            return ok_result(
                {
                    "dataset_id": dataset_id,
                    "title": f"OSM extract {dataset_id}",
                    "license_spdx": "ODbL-1.0",
                    "attribution": "© OpenStreetMap contributors",
                    "asset_ids": [],
                }
            )
        return ok_result(
            {
                "dataset_id": dataset_id,
                "title": f"OSM extract {dataset_id}",
                "license_spdx": "ODbL-1.0",
                "attribution": "© OpenStreetMap contributors",
                "asset_ids": ["overpass.geojson"],
            }
        )

    def get_assets(self, dataset_id: str) -> tuple[bool, dict[str, Any]]:
        ok, payload = self.get_metadata(dataset_id)
        if not ok:
            return ok, payload
        return ok_result({"dataset_id": dataset_id, "asset_ids": payload.get("asset_ids", [])})

    def download(self, dataset_id: str, asset_id: str, sandbox_dir: str) -> tuple[bool, dict[str, Any]]:
        """Structured re-fetch of the recorded search query (no guessing).

        The dataset id encodes the search bbox+tags; every piece is
        re-validated (allowlist, lengths, bbox, area cap) before any
        egress. The Overpass JSON response converts deterministically to
        GeoJSON and lands sandbox-scoped as ``overpass.geojson``.
        """
        decoded = decode_overpass_dataset_id(dataset_id)
        if decoded is None or asset_id != "overpass.geojson":
            return error_result(ProviderError.INVALID_QUERY, "overpass download needs the recorded search id + asset")
        tags, bbox = decoded
        ok, ql = build_overpass_ql(bbox, tags)
        if not ok:
            return error_result(ProviderError.INVALID_QUERY, ql)
        url = self._query_url(ql)
        result = fetch_url(
            url, self.host_allowlist(), timeout_s=self.limits().timeout_s, max_bytes=self.limits().max_bytes
        )
        if not result.ok:
            return error_result(ProviderError.PROVIDER_OFFLINE, result.error or "")
        try:
            payload = json.loads(result.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return error_result(ProviderError.PROVIDER_OFFLINE, "invalid-json")
        try:
            geojson, counts = overpass_json_to_geojson(payload)
            body = json.dumps(geojson, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            return error_result(ProviderError.PROVIDER_OFFLINE, f"convert-failed: {exc}")
        ok_write, written = _write_sandbox_bytes(body, sandbox_dir, "overpass.geojson", self.limits().max_bytes)
        if not ok_write:
            return ok_write, written
        written["features"] = counts["features"]
        written["skipped_relations"] = counts["skipped_relations"]
        return True, written

    def attribution(self, dataset_id: str) -> tuple[bool, dict[str, Any]]:
        _ = dataset_id
        return ok_result({"attribution": "© OpenStreetMap contributors"})

    def license(self, dataset_id: str) -> tuple[bool, dict[str, Any]]:
        _ = dataset_id
        return ok_result({"spdx": "ODbL-1.0", "attribution": "© OpenStreetMap contributors"})


class NominatimAdapter:
    """Policy-compliant Nominatim geocoder (place → bbox)."""

    def __init__(self) -> None:
        self._last_request_at: float = 0.0
        self._cache: dict[str, tuple[bool, dict[str, Any]]] = {}

    def provider_id(self) -> str:
        return "osm.nominatim"

    def provider_version(self) -> str:
        return PROVIDER_VERSION

    def host_allowlist(self) -> tuple[str, ...]:
        return (NOMINATIM_HOST,)

    def limits(self) -> ProviderLimits:
        return ProviderLimits(
            max_results=10,
            timeout_s=15.0,
            retries=1,
            cache_ttl_s=86400,
            nominatim_req_per_s=1.0,
        )

    def _throttle(self) -> None:
        gap = 1.0 / max(self.limits().nominatim_req_per_s, 0.01)
        wait = self._last_request_at + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def search(self, query: SearchQuery, page_token: str | None = None) -> tuple[bool, dict[str, Any]]:
        _ = page_token
        errors = validate_search_query(query, self.limits())
        if errors:
            return error_result(ProviderError.INVALID_QUERY, "; ".join(errors))
        if not query.place:
            return error_result(ProviderError.INVALID_QUERY, "place required for nominatim")
        if query.place in self._cache:
            return self._cache[query.place]
        self._throttle()
        params = urllib.parse.urlencode({"q": query.place, "format": "jsonv2", "limit": str(min(query.limit, 10))})
        url = f"https://{NOMINATIM_HOST}/search?{params}"
        result = fetch_url(url, self.host_allowlist(), timeout_s=self.limits().timeout_s, max_bytes=1024 * 1024)
        if not result.ok:
            out = error_result(ProviderError.PROVIDER_OFFLINE, result.error or "")
            self._cache[query.place] = out
            return out
        try:
            hits = json.loads(result.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            out = error_result(ProviderError.PROVIDER_OFFLINE, "invalid-json")
            self._cache[query.place] = out
            return out
        if not isinstance(hits, list):
            out = error_result(ProviderError.PROVIDER_OFFLINE, "malformed-response")
            self._cache[query.place] = out
            return out
        results: list[dict[str, Any]] = []
        for hit in hits[:10]:
            if not isinstance(hit, dict):
                continue
            box = hit.get("boundingbox")
            bbox = None
            if isinstance(box, list) and len(box) == 4:
                try:
                    south, north, west, east = (float(v) for v in box)
                    bbox = [west, south, east, north]
                except (ValueError, TypeError):
                    bbox = None
            results.append(
                {
                    "dataset_id": f"nominatim:{hit.get('place_id', '')}",
                    "title": str(hit.get("display_name", query.place)),
                    "provider_id": self.provider_id(),
                    "bbox": bbox,
                    "license_spdx": "ODbL-1.0",
                }
            )
        out = ok_result({"results": results, "total": len(results)})
        self._cache[query.place] = out
        return out

    def get_metadata(self, dataset_id: str) -> tuple[bool, dict[str, Any]]:
        if not dataset_id.startswith("nominatim:"):
            return error_result(ProviderError.INVALID_QUERY, "bad dataset_id")
        return ok_result(
            {
                "dataset_id": dataset_id,
                "title": f"Nominatim result {dataset_id}",
                "license_spdx": "ODbL-1.0",
                "attribution": "© OpenStreetMap contributors",
                "asset_ids": [],
            }
        )

    def get_assets(self, dataset_id: str) -> tuple[bool, dict[str, Any]]:
        _ = dataset_id
        return ok_result({"dataset_id": dataset_id, "asset_ids": []})

    def download(self, dataset_id: str, asset_id: str, sandbox_dir: str) -> tuple[bool, dict[str, Any]]:
        _ = (dataset_id, asset_id, sandbox_dir)
        return error_result(ProviderError.INVALID_QUERY, "nominatim supplies geocoding only (no assets)")

    def attribution(self, dataset_id: str) -> tuple[bool, dict[str, Any]]:
        _ = dataset_id
        return ok_result({"attribution": "© OpenStreetMap contributors"})

    def license(self, dataset_id: str) -> tuple[bool, dict[str, Any]]:
        _ = dataset_id
        return ok_result({"spdx": "ODbL-1.0", "attribution": "© OpenStreetMap contributors"})


__all__ = [
    "OverpassAdapter",
    "NominatimAdapter",
    "build_overpass_ql",
    "encode_overpass_dataset_id",
    "decode_overpass_dataset_id",
    "overpass_json_to_geojson",
    "ALLOWLISTED_TAG_KEYS",
    "OVERPASS_HOSTS",
    "NOMINATIM_HOST",
]
