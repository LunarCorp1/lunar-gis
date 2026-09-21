"""Lunar GIS data provider adapters (lazy-loaded, see registry)."""

from lunar_gis.data.adapters.registry import get, ids, register_provider

__all__ = ["get", "ids", "register_provider"]
