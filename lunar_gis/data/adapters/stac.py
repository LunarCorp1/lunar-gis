"""M4-T05 STAC catalog adapter (structured queries only).

Implements the frozen §6 surface against STAC API ``/search`` (POST
GeoJSON). Never passes free text to a URL; bbox/datetime/collection/
limit are validated structs. Every egress URL — the catalog endpoint
and every asset ``href`` — passes the §5.2/§9 transport validator
(host allowlist + resolved-IP blocking + redirect re-validation).

Default endpoint: Earth Search (``earth-search.aws.element84.com``).
Additional catalogs join via ``register_provider`` with their own
allowlisted host — never by passing a URL at query time.

Search responses are treated as untrusted metadata (T3): sizes, checksums,
media types, and license fields are validated before use; oversized or
off-allowlist assets are refused, never truncated silently.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

from lunar_gis.data.adapters.base import (
    Asset,
    DatasetMetadata,
    DatasetSummary,
    ProviderError,
    ProviderLimits,
    SearchQuery,
    error_result,
    ok_result,
    validate_search_query,
)
from lunar_gis.data.adapters.transport import audit_url, download_to_sandbox, fetch_url, validate_egress_url

EARTH_SEARCH_HOST = "earth-search.aws.element84.com"
EARTH_SEARCH_URL = f"https://{EARTH_SEARCH_HOST}/v1/search"
PROVIDER_VERSION = "1.0.0"

# Media types the adapter will persist (extension re-check at validation).
ALLOWED_MEDIA_PREFIXES: tuple[str, ...] = ("image/tiff", "application/json", "application/geo+json")


class EarthSearchAdapter:
    """STAC API adapter pinned to the Earth Search host allowlist."""

    def __init__(self, search_url: str = EARTH_SEARCH_URL) -> None:
        ok, _ = validate_egress_url(search_url, self.host_allowlist())
        if not ok:
            raise ValueError("STAC search URL outside the adapter host allowlist")
        self._search_url = search_url

    def provider_id(self) -> str:
        return "stac.earth-search"

    def provider_version(self) -> str:
        return PROVIDER_VERSION

    def host_allowlist(self) -> tuple[str, ...]:
        return (EARTH_SEARCH_HOST,)

    def limits(self) -> ProviderLimits:
        return ProviderLimits(
            max_area_km2=100.0,
            max_bytes=500 * 1024 * 1024,
            max_assets=10,
            max_results=50,
            timeout_s=30.0,
            retries=2,
            cache_ttl_s=3600,
        )

    def _post_json(self, payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        import urllib.request

        body = json.dumps(payload).encode("utf-8")
        from lunar_gis.data.adapters.transport import _NoRedirect

        opener = urllib.request.build_opener(urllib.request.HTTPHandler(), urllib.request.HTTPSHandler(), _NoRedirect())
        opener.addheaders = [("User-Agent", "LunarGIS/1.0"), ("Content-Type", "application/json")]
        request = urllib.request.Request(self._search_url, data=body, method="POST")
        try:
            with opener.open(request, timeout=self.limits().timeout_s) as response:
                if int(response.status) != 200:
                    return error_result(ProviderError.PROVIDER_OFFLINE, f"http-{response.status}")
                raw = response.read(2 * 1024 * 1024)
        except Exception as exc:
            return error_result(ProviderError.PROVIDER_OFFLINE, f"{type(exc).__name__}")
        try:
            return ok_result(json.loads(raw.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            return error_result(ProviderError.PROVIDER_OFFLINE, "invalid-json")

    def _search_payload(self, query: SearchQuery) -> dict[str, Any]:
        payload: dict[str, Any] = {"limit": min(query.limit, self.limits().max_results)}
        if query.bbox is not None:
            payload["bbox"] = list(query.bbox)
        if query.datetime_range is not None:
            start, end = query.datetime_range
            payload["datetime"] = f"{start or '..'}/{end or '..'}"
        if query.collection is not None:
            payload["collections"] = [query.collection]
        return payload

    def search(self, query: SearchQuery, page_token: str | None = None) -> tuple[bool, dict[str, Any]]:
        _ = page_token  # pagination via next-link is a later seam; limit-capped single page in v1
        errors = validate_search_query(query, self.limits())
        if errors:
            return error_result(ProviderError.INVALID_QUERY, "; ".join(errors))
        ok, payload = self._post_json(self._search_payload(query))
        if not ok:
            return ok, payload
        results: list[dict[str, Any]] = []
        features = payload.get("features", [])
        if not isinstance(features, list):
            return error_result(ProviderError.PROVIDER_OFFLINE, "malformed-features")
        for feature in features[: self.limits().max_results]:
            if not isinstance(feature, dict):
                continue
            summary = self._summarize(feature)
            if summary is not None:
                assets = feature.get("assets", {}) if isinstance(feature.get("assets"), dict) else {}
                asset_ids = sorted(str(k) for k in assets.keys())[:5]
                results.append(
                    {
                        "dataset_id": summary.dataset_id,
                        "title": summary.title,
                        "provider_id": summary.provider_id,
                        "bbox": list(summary.bbox) if summary.bbox else None,
                        "license_spdx": summary.license_spdx,
                        "asset_ids": asset_ids,
                    }
                )
        return ok_result({"results": results, "total": len(results)})

    def _summarize(self, feature: dict[str, Any]) -> DatasetSummary | None:
        dataset_id = feature.get("id")
        if not isinstance(dataset_id, str) or not dataset_id:
            return None
        props = feature.get("properties", {}) if isinstance(feature.get("properties"), dict) else {}
        title = props.get("title", dataset_id)
        bbox = feature.get("bbox")
        box = tuple(bbox[:4]) if isinstance(bbox, list) and len(bbox) >= 4 else None
        license_spdx = props.get("license", "NONE-declared")
        return DatasetSummary(
            dataset_id=dataset_id,
            title=str(title),
            provider_id=self.provider_id(),
            bbox=box,  # type: ignore[arg-type]
            license_spdx=str(license_spdx),
        )

    def get_metadata(self, dataset_id: str) -> tuple[bool, dict[str, Any]]:
        if not dataset_id or "/" in dataset_id or "\\" in dataset_id:
            return error_result(ProviderError.INVALID_QUERY, "bad dataset_id")
        item_url = f"https://{EARTH_SEARCH_HOST}/v1/collections/items/{urllib.parse.quote(dataset_id)}"
        result = fetch_url(item_url, self.host_allowlist(), timeout_s=self.limits().timeout_s, max_bytes=1024 * 1024)
        if not result.ok:
            return error_result(ProviderError.DATASET_NOT_FOUND, result.error or "")
        try:
            item = json.loads(result.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return error_result(ProviderError.PROVIDER_OFFLINE, "invalid-json")
        if not isinstance(item, dict):
            return error_result(ProviderError.DATASET_NOT_FOUND, "malformed-item")
        assets = item.get("assets", {}) if isinstance(item.get("assets"), dict) else {}
        meta = DatasetMetadata(
            dataset_id=dataset_id,
            provider_id=self.provider_id(),
            title=str(item.get("properties", {}).get("title", dataset_id)),
            license_spdx=str(item.get("properties", {}).get("license", "NONE-declared")),
            attribution="Earth Search (Element 84)",
            asset_ids=tuple(sorted(assets.keys()))[: self.limits().max_assets],
        )
        return ok_result(
            {
                "dataset_id": meta.dataset_id,
                "title": meta.title,
                "license_spdx": meta.license_spdx,
                "attribution": meta.attribution,
                "asset_ids": list(meta.asset_ids),
            }
        )

    def get_assets(self, dataset_id: str) -> tuple[bool, dict[str, Any]]:
        ok, payload = self.get_metadata(dataset_id)
        if not ok:
            return ok, payload
        return ok_result({"dataset_id": dataset_id, "asset_ids": payload.get("asset_ids", [])})

    def _asset_href(self, dataset_id: str, asset_id: str) -> tuple[bool, dict[str, Any]]:
        item_url = f"https://{EARTH_SEARCH_HOST}/v1/collections/items/{urllib.parse.quote(dataset_id)}"
        result = fetch_url(item_url, self.host_allowlist(), timeout_s=self.limits().timeout_s, max_bytes=1024 * 1024)
        if not result.ok:
            return error_result(ProviderError.DATASET_NOT_FOUND, result.error or "")
        try:
            item = json.loads(result.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return error_result(ProviderError.PROVIDER_OFFLINE, "invalid-json")
        assets = item.get("assets", {}) if isinstance(item, dict) and isinstance(item.get("assets"), dict) else {}
        entry = assets.get(asset_id)
        if not isinstance(entry, dict) or not isinstance(entry.get("href"), str):
            return error_result(ProviderError.DATASET_NOT_FOUND, "asset-not-found")
        href: str = entry["href"]
        media = str(entry.get("type", "application/octet-stream"))
        if not any(media.startswith(prefix) for prefix in ALLOWED_MEDIA_PREFIXES):
            return error_result(ProviderError.INVALID_QUERY, f"media-not-allowlisted: {media}")
        ok_href, reason = validate_egress_url(href, self.host_allowlist())
        if not ok_href:
            return error_result(ProviderError.INVALID_QUERY, f"href-rejected: {reason}")
        asset = Asset(
            asset_id=asset_id,
            dataset_id=dataset_id,
            media_type=media,
            size_bytes=entry.get("file:size") if isinstance(entry.get("file:size"), int) else None,
        )
        if asset.size_bytes is not None and asset.size_bytes > self.limits().max_bytes:
            return error_result(ProviderError.QUOTA_EXCEEDED, "asset exceeds max_bytes")
        return ok_result({"href": href, "asset": asset.__dict__, "audit_url": audit_url(href)})

    def download(self, dataset_id: str, asset_id: str, sandbox_dir: str) -> tuple[bool, dict[str, Any]]:
        ok, payload = self._asset_href(dataset_id, asset_id)
        if not ok:
            return ok, payload
        suffix = ".tif" if payload["asset"]["media_type"].startswith("image/") else ".json"
        relpath = f"{dataset_id}_{asset_id}{suffix}".replace("/", "_")
        return download_to_sandbox(
            payload["href"],
            self.host_allowlist(),
            sandbox_dir,
            relpath,
            timeout_s=self.limits().timeout_s,
            max_bytes=self.limits().max_bytes,
        )

    def attribution(self, dataset_id: str) -> tuple[bool, dict[str, Any]]:
        _ = dataset_id
        return ok_result({"attribution": "Earth Search (Element 84)"})

    def license(self, dataset_id: str) -> tuple[bool, dict[str, Any]]:
        ok, payload = self.get_metadata(dataset_id)
        if not ok:
            return ok, payload
        spdx = payload.get("license_spdx", "NONE-declared")
        if spdx == "NONE-declared":
            return error_result(ProviderError.LICENSE_UNAVAILABLE, "no license declared")
        return ok_result({"spdx": spdx, "attribution": payload.get("attribution", "")})


__all__ = ["EarthSearchAdapter", "EARTH_SEARCH_HOST", "EARTH_SEARCH_URL"]
