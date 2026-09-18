"""Minimal QGIS fakes for offline tests — interfaces consumed by ProjectContext and data.discovery_qgis."""

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


class FakeExtent:
    """Mimics qgis.core.QgsRectangle minimum/maximum accessors."""

    def __init__(
        self,
        xmin: float = 0.0,
        ymin: float = 0.0,
        xmax: float = 1.0,
        ymax: float = 1.0,
        raise_exc: bool = False,
    ):
        self._box = (xmin, ymin, xmax, ymax)
        self._raise_exc = raise_exc

    def _guard(self) -> None:
        if self._raise_exc:
            raise RuntimeError("extent accessor failed")

    def xMinimum(self) -> float:
        self._guard()
        return self._box[0]

    def yMinimum(self) -> float:
        self._guard()
        return self._box[1]

    def xMaximum(self) -> float:
        self._guard()
        return self._box[2]

    def yMaximum(self) -> float:
        self._guard()
        return self._box[3]


class FakeField:
    """Mimics qgis.core.QgsField typeName()."""

    def __init__(self, name: str, type_name: str = "String"):
        self._name = name
        self._type_name = type_name

    def name(self) -> str:
        return self._name

    def typeName(self) -> str:
        return self._type_name


class FakeFields:
    """Mimics qgis.core.QgsFields names()/field()."""

    def __init__(self, fields: list[FakeField] | None = None, raise_exc: bool = False):
        self._fields = fields if fields is not None else [FakeField("id", "Int")]
        self._raise_exc = raise_exc

    def names(self) -> list[str]:
        if self._raise_exc:
            raise RuntimeError("fields names failed")
        return [f.name() for f in self._fields]

    def field(self, name: str) -> FakeField | None:
        for f in self._fields:
            if f.name() == name:
                return f
        return None


class FakeTemporalProperties:
    """Mimics QgsMapLayer.temporalProperties().isActive()."""

    def __init__(self, active: bool = False):
        self._active = active

    def isActive(self) -> bool:
        return self._active


class FakeLayer:
    """Mimics the QgsMapLayer subset used by ProjectContext and discovery_qgis."""

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
        extent: FakeExtent | None = None,
        has_extent: bool = True,
        extent_raise: bool = False,
        fields: FakeFields | None = None,
        has_fields: bool = True,
        fields_raise: bool = False,
        is_valid: bool = True,
        valid_raise: bool = False,
        source: str = "",
        source_raise: bool = False,
        temporal_active: bool | None = None,
        has_temporal: bool = True,
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
        self._extent = extent
        self._has_extent = has_extent
        self._extent_raise = extent_raise
        self._fields = fields
        self._has_fields = has_fields
        self._fields_raise = fields_raise
        self._is_valid = is_valid
        self._valid_raise = valid_raise
        self._source = source
        self._source_raise = source_raise
        self._temporal_active = temporal_active
        self._has_temporal = has_temporal

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
        if name == "extent":
            if not self._has_extent:
                raise AttributeError(name)
            if self._extent_raise:

                def _raise3() -> FakeExtent:
                    raise RuntimeError("extent failed")

                return _raise3
            box = self._extent if self._extent is not None else FakeExtent()
            return lambda: box
        if name == "fields":
            if not self._has_fields:
                raise AttributeError(name)
            if self._fields_raise:

                def _raise4() -> FakeFields:
                    raise RuntimeError("fields failed")

                return _raise4
            fields = self._fields if self._fields is not None else FakeFields([])
            return lambda: fields
        if name == "isValid":
            if self._valid_raise:

                def _raise5() -> bool:
                    raise RuntimeError("isValid failed")

                return _raise5
            valid = self._is_valid
            return lambda: valid
        if name == "source":
            if self._source_raise:

                def _raise6() -> str:
                    raise RuntimeError("source failed")

                return _raise6
            source = self._source
            return lambda: source
        if name == "temporalProperties":
            if not self._has_temporal or self._temporal_active is None:
                raise AttributeError(name)
            active = self._temporal_active
            return lambda: FakeTemporalProperties(active=active)
        raise AttributeError(name)


class FakeProject:
    """Mimics QgsProject with mapLayers()."""

    def __init__(
        self,
        layers: dict[str, FakeLayer] | None = None,
        dirty: bool = False,
        has_dirty: bool = True,
    ):
        self._layers: dict[str, FakeLayer] = layers or {}
        self._dirty = dirty
        self._has_dirty = has_dirty

    def mapLayers(self) -> dict[str, FakeLayer]:
        return self._layers

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        if name == "isDirty":
            if not self._has_dirty:
                raise AttributeError(name)
            dirty = self._dirty
            return lambda: dirty
        raise AttributeError(name)
