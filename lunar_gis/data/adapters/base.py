"""M4-T05 provider adapter interface (QGIS-free, frozen per M4 §6).

Adapters accept dataset IDs / structured queries only — never raw URLs
(URL fields in schemas are rejected). All addressing flows through
``(provider_id, dataset_id, asset_id)`` identity + the adapter's frozen
host allowlist. Every method returns ``(ok, payload | error_code)``
with the closed error taxonomy.

Method names normative; signatures JSON-shaped (registry-validator
compatible). Adapters MUST NOT: open GUI, read/write outside the given
sandbox, store credentials, log URLs with query secrets, perform GIS
math (they fetch bytes; QGIS interprets them).

Stdlib only. No ``qgis.*``, no network clients directly (egress only
inside adapter transport under the §5.2/§9 wrapper in ``transport.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class ProviderError(str, Enum):
    """Closed error taxonomy (M4 §6)."""

    PROVIDER_OFFLINE = "PROVIDER_OFFLINE"
    DATASET_NOT_FOUND = "DATASET_NOT_FOUND"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    RATE_LIMITED = "RATE_LIMITED"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
    LICENSE_UNAVAILABLE = "LICENSE_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    INVALID_QUERY = "INVALID_QUERY"


# Acquisition-scope error → MISSING sub-reason mapping (§6, §3.3).
ERROR_TO_MISSING: dict[str, str] = {
    ProviderError.DATASET_NOT_FOUND.value: "no-layer",
    ProviderError.LICENSE_UNAVAILABLE.value: "license-unavailable",
    ProviderError.PROVIDER_OFFLINE.value: "provider-offline",
}

# Retryable at download (not classification) — §3.3 retry scopes.
RETRYABLE_ERRORS: frozenset[str] = frozenset(
    {
        ProviderError.TIMEOUT.value,
        ProviderError.RATE_LIMITED.value,
        ProviderError.QUOTA_EXCEEDED.value,
    }
)


@dataclass(frozen=True)
class ProviderLimits:
    """Mandatory limit fields (quota + security caps, M4 §6)."""

    max_area_km2: float = 100.0
    max_bytes: int = 500 * 1024 * 1024
    max_assets: int = 10
    max_results: int = 50
    timeout_s: float = 30.0
    retries: int = 2
    cache_ttl_s: int = 3600
    max_archive_members: int = 1000
    max_unpacked_bytes: int = 1024 * 1024 * 1024
    max_decompression_ratio: float = 100.0
    nominatim_req_per_s: float = 1.0


@dataclass(frozen=True)
class DatasetSummary:
    dataset_id: str
    title: str
    provider_id: str
    bbox: tuple[float, float, float, float] | None = None
    crs_authid: str | None = None
    datetime_range: tuple[str | None, str | None] | None = None
    license_spdx: str = "NONE-declared"


@dataclass(frozen=True)
class DatasetMetadata:
    dataset_id: str
    provider_id: str
    title: str
    license_spdx: str
    attribution: str
    asset_ids: tuple[str, ...] = ()
    crs_authid: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    dataset_version: str | None = None


@dataclass(frozen=True)
class Asset:
    asset_id: str
    dataset_id: str
    media_type: str
    size_bytes: int | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class LocalFile:
    """Download result: sandbox-relative path only (never absolute)."""

    sandbox_relpath: str
    size_bytes: int
    sha256_actual: str


@dataclass(frozen=True)
class SearchQuery:
    """Structured query only (M4 §6). No free text except Nominatim place."""

    bbox: tuple[float, float, float, float] | None = None
    datetime_range: tuple[str | None, str | None] | None = None
    collection: str | None = None
    limit: int = 10
    tags: tuple[tuple[str, str], ...] = ()
    place: str | None = None  # Nominatim only: URL-encoded + capped


@runtime_checkable
class ProviderAdapter(Protocol):
    """Frozen adapter surface (method names normative, M4 §6)."""

    def provider_id(self) -> str: ...
    def provider_version(self) -> str: ...
    def host_allowlist(self) -> tuple[str, ...]: ...
    def limits(self) -> ProviderLimits: ...
    def search(self, query: SearchQuery, page_token: str | None = None) -> tuple[bool, dict[str, Any]]: ...
    def get_metadata(self, dataset_id: str) -> tuple[bool, dict[str, Any]]: ...
    def get_assets(self, dataset_id: str) -> tuple[bool, dict[str, Any]]: ...
    def download(self, dataset_id: str, asset_id: str, sandbox_dir: str) -> tuple[bool, dict[str, Any]]: ...
    def attribution(self, dataset_id: str) -> tuple[bool, dict[str, Any]]: ...
    def license(self, dataset_id: str) -> tuple[bool, dict[str, Any]]: ...


def validate_search_query(query: SearchQuery, limits: ProviderLimits) -> list[str]:
    """Validate a structured query against adapter limits. Empty = valid."""
    errors: list[str] = []
    if query.limit < 1:
        errors.append("limit: must be >= 1")
    if query.limit > limits.max_results:
        errors.append(f"limit: {query.limit} exceeds max_results {limits.max_results}")
    if query.bbox is not None:
        if len(query.bbox) != 4:
            errors.append("bbox: must have 4 elements")
        else:
            xmin, ymin, xmax, ymax = query.bbox
            if not (xmin < xmax and ymin < ymax):
                errors.append("bbox: requires xmin<xmax and ymin<ymax")
    if query.place is not None:
        if len(query.place) > 200:
            errors.append("place: exceeds 200 chars")
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ,.-_'()")
        if any(c not in allowed for c in query.place):
            errors.append("place: unsupported charset")
    return errors


def error_result(code: ProviderError, detail: str = "") -> tuple[bool, dict[str, Any]]:
    return False, {"error": code.value, "detail": detail}


def ok_result(payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    return True, payload


__all__ = [
    "ProviderError",
    "ERROR_TO_MISSING",
    "RETRYABLE_ERRORS",
    "ProviderLimits",
    "DatasetSummary",
    "DatasetMetadata",
    "Asset",
    "LocalFile",
    "SearchQuery",
    "ProviderAdapter",
    "validate_search_query",
    "error_result",
    "ok_result",
]
