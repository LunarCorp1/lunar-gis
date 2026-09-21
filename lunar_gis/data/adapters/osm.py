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
    return True, "[out:json][timeout:25];(" + "".join(clauses) + ");out body;"


class OverpassAdapter:
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
                "dataset_id": f"osm:{query.tags[0][0]}={query.tags[0][1]}",
                "title": f"OSM {query.tags[0][0]}={query.tags[0][1]} in bbox",
                "provider_id": self.provider_id(),
                "bbox": list(query.bbox),
                "license_spdx": "ODbL-1.0",
                "element_count": len(elements),
            }
        ]
        return ok_result({"results": results, "total": 1})

    def get_metadata(self, dataset_id: str) -> tuple[bool, dict[str, Any]]:
        if not dataset_id.startswith("osm:"):
            return error_result(ProviderError.INVALID_QUERY, "bad dataset_id")
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
        # v1 seam: structured re-fetch for the recorded query is owned by
        # the acquisition workflow (M4-T07); direct id-only download refuses
        # rather than guessing parameters.
        _ = (dataset_id, asset_id, sandbox_dir)
        return error_result(ProviderError.INVALID_QUERY, "overpass download requires the recorded query (see search)")

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
    "ALLOWLISTED_TAG_KEYS",
    "OVERPASS_HOSTS",
    "NOMINATIM_HOST",
]
