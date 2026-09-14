"""Minimal QGIS fakes for offline tests — only interfaces consumed by ProjectContext."""

from __future__ import annotations


class FakeCrs:
    """Mimics qgis.core.QgsCoordinateReferenceSystem authid()."""

    def __init__(self, authid: str = "EPSG:4326", raise_exc: bool = False):
        self._authid = authid
        self._raise_exc = raise_exc

    def authid(self) -> str:
        if self._raise_exc:
            raise RuntimeError("crs authid failed")
        return self._authid


class FakeLayer:
    """Mimics QgsMapLayer subset used by ProjectContext.layer_summaries()."""

    def __init__(
        self,
        layer_id: str = "lid",
        name: str = "layer",
        provider: str = "ogr",
        crs_authid: str | None = "EPSG:4326",
        crs_raise: bool = False,
        geometry_type: int | None = 0,
        has_geometry_type: bool = True,
        geometry_raise: bool = False,
        feature_count: int | None = 5,
        has_feature_count: bool = True,
        feature_raise: bool = False,
    ):
        self._layer_id = layer_id
        self._name = name
        self._provider = provider
        self._crs_authid = crs_authid
        self._crs_raise = crs_raise
        self._geometry_type = geometry_type
        self._has_geometry_type = has_geometry_type
        self._geometry_raise = geometry_raise
        self._feature_count = feature_count
        self._has_feature_count = has_feature_count
        self._feature_raise = feature_raise

    # Required API
    def id(self) -> str:
        return self._layer_id

    def name(self) -> str:
        return self._name

    def providerType(self) -> str:
        return self._provider

    def crs(self) -> FakeCrs:
        if self._crs_raise:
            raise RuntimeError("crs failed")
        # authid may be None to simulate missing CRS — mimic qgis returning "" for invalid
        # FakeCrs will store whatever string we give; for None we simulate raise or empty
        if self._crs_authid is None:
            return FakeCrs(authid="", raise_exc=False)
        return FakeCrs(authid=self._crs_authid, raise_exc=False)

    # Optional API — geometryType
    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        if name == "geometryType":
            if not self._has_geometry_type:
                raise AttributeError(name)
            if self._geometry_raise:

                def _raise() -> int:
                    raise RuntimeError("geometryType failed")

                return _raise
            return lambda: self._geometry_type  # type: ignore[return-value]
        if name == "featureCount":
            if not self._has_feature_count:
                raise AttributeError(name)
            if self._feature_raise:

                def _raise2() -> int:
                    raise RuntimeError("featureCount failed")

                return _raise2
            return lambda: self._feature_count  # type: ignore[return-value]
        raise AttributeError(name)


class FakeProject:
    """Mimics QgsProject with mapLayers()."""

    def __init__(self, layers: dict[str, FakeLayer] | None = None):
        self._layers: dict[str, FakeLayer] = layers or {}

    def mapLayers(self) -> dict[str, FakeLayer]:
        return self._layers
