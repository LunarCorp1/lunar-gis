"""M4-T05 adapter registry: lazy loading, no provider import at data time.

Satisfies M4 §11: ``import lunar_gis.data`` stays QGIS-optional and
provider-free. Adapters load on first ``get()`` by provider id.

Public API:
- ADAPTER_IDS: tuple of registered provider ids
- get(provider_id) -> ProviderAdapter (raises KeyError on unknown)
- register_provider(provider_id, loader) -> None (tests/extensions)
"""

from __future__ import annotations

from typing import Any, Callable

_LOADERS: dict[str, Callable[[], Any]] = {}


def _stac_earth_search() -> Any:
    from lunar_gis.data.adapters.stac import EarthSearchAdapter

    return EarthSearchAdapter()


def _osm_overpass() -> Any:
    from lunar_gis.data.adapters.osm import OverpassAdapter

    return OverpassAdapter()


def _osm_nominatim() -> Any:
    from lunar_gis.data.adapters.osm import NominatimAdapter

    return NominatimAdapter()


_LOADERS["stac.earth-search"] = _stac_earth_search
_LOADERS["osm.overpass"] = _osm_overpass
_LOADERS["osm.nominatim"] = _osm_nominatim


def register_provider(provider_id: str, loader: Callable[[], Any]) -> None:
    if not provider_id or not isinstance(provider_id, str):
        raise ValueError("provider_id must be a non-empty string")
    _LOADERS[provider_id] = loader


def get(provider_id: str) -> Any:
    try:
        loader = _LOADERS[provider_id]
    except KeyError:
        raise KeyError(f"Unknown provider: {provider_id}") from None
    return loader()


def ids() -> tuple[str, ...]:
    return tuple(sorted(_LOADERS))


__all__ = ["get", "ids", "register_provider"]
