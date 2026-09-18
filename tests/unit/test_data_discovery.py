"""Unit tests for M4-T02 QGIS project discovery (offline fakes) plus one
QGIS-runtime test that skips when QGIS is unavailable (existing convention)."""

from __future__ import annotations

import pytest

from lunar_gis.data.contracts import Reachability, StorageKind, ValueState
from lunar_gis.data.discovery_qgis import discover_project
from tests.fixtures.qgis_fakes import FakeExtent, FakeFields, FakeField, FakeLayer, FakeProject

TAKEN_AT = "2026-02-01T12:00:00+00:00"


def _project(*layers: FakeLayer, **kwargs) -> FakeProject:
    mapping = {layer.id(): layer for layer in layers}
    return FakeProject(layers=mapping, **kwargs)


@pytest.mark.unit
class TestOrdering:
    def test_empty_project(self) -> None:
        inventory = discover_project(_project(), taken_at=TAKEN_AT)
        assert inventory.records == ()
        assert inventory.total_count == 0
        assert inventory.truncated is False
        assert inventory.taken_at == TAKEN_AT

    def test_layer_id_order_despite_insertion(self) -> None:
        b = FakeLayer(layer_id="b", name="b")
        a = FakeLayer(layer_id="a", name="a")
        inventory = discover_project(_project(b, a), taken_at=TAKEN_AT)
        assert [r.layer_id for r in inventory.records] == ["a", "b"]

    def test_multiple_layers(self) -> None:
        inventory = discover_project(
            _project(FakeLayer(layer_id="c"), FakeLayer(layer_id="a"), FakeLayer(layer_id="b")),
            taken_at=TAKEN_AT,
        )
        assert [r.layer_id for r in inventory.records] == ["a", "b", "c"]
        assert inventory.total_count == 3


@pytest.mark.unit
class TestRecordFields:
    def test_full_vector_record(self) -> None:
        layer = FakeLayer(
            layer_id="roads",
            name="Roads",
            provider="ogr",
            geometry_type=2,
            feature_count=42,
            crs_authid="EPSG:4326",
            extent=FakeExtent(0.0, 0.0, 10.0, 20.0),
            fields=FakeFields([FakeField("id", "Int"), FakeField("name", "String")]),
            is_valid=True,
            source="/data/roads.gpkg",
            temporal_active=False,
        )
        (record,) = discover_project(_project(layer), taken_at=TAKEN_AT).records
        assert record.layer_id == "roads"
        assert record.name == "Roads"
        assert record.provider == "ogr"
        assert record.geometry_type == "2"  # opaque, never canonicalized here
        assert record.crs_authid == "EPSG:4326"
        assert record.crs_known is True
        assert record.feature_count == 42
        assert record.feature_count_state == ValueState.KNOWN
        assert record.extent is not None
        assert (record.extent.xmin, record.extent.ymax) == (0.0, 20.0)
        assert record.extent.crs_authid == "EPSG:4326"
        assert record.extent_state == ValueState.KNOWN
        assert [(f.name, f.type) for f in record.fields or ()] == [("id", "Int"), ("name", "String")]
        assert record.fields_state == ValueState.KNOWN
        assert record.storage == StorageKind.FILE
        assert record.has_time is False
        assert record.valid is True
        assert record.source_redacted == "/data/roads.gpkg"

    def test_invalid_layer(self) -> None:
        layer = FakeLayer(is_valid=False)
        (record,) = discover_project(_project(layer), taken_at=TAKEN_AT).records
        assert record.valid is False
        # non-remote invalid stays UNKNOWN (no probing to declare unreachable)
        assert record.reachable == Reachability.UNKNOWN

    def test_invalid_remote_is_unreachable(self) -> None:
        layer = FakeLayer(provider="wfs", is_valid=False)
        (record,) = discover_project(_project(layer), taken_at=TAKEN_AT).records
        assert record.storage == StorageKind.REMOTE_SERVICE
        assert record.reachable == Reachability.KNOWN_UNREACHABLE

    def test_storage_mapping(self) -> None:
        def storage_of(provider: str) -> StorageKind:
            records = discover_project(_project(FakeLayer(provider=provider)), taken_at=TAKEN_AT).records
            return records[0].storage

        assert storage_of("memory") == StorageKind.MEMORY
        assert storage_of("postgres") == StorageKind.DATABASE
        assert storage_of("wms") == StorageKind.REMOTE_SERVICE
        assert storage_of("novel") == StorageKind.UNKNOWN


@pytest.mark.unit
class TestUnknownStates:
    def test_count_minus_one_is_unknown(self) -> None:
        layer = FakeLayer(feature_count=-1)
        (record,) = discover_project(_project(layer), taken_at=TAKEN_AT).records
        assert record.feature_count is None
        assert record.feature_count_state == ValueState.UNKNOWN

    def test_count_missing_is_unavailable(self) -> None:
        layer = FakeLayer(has_feature_count=False)
        (record,) = discover_project(_project(layer), taken_at=TAKEN_AT).records
        assert record.feature_count is None
        assert record.feature_count_state == ValueState.UNAVAILABLE

    def test_empty_authid_normalized(self) -> None:
        layer = FakeLayer(crs_authid="")
        (record,) = discover_project(_project(layer), taken_at=TAKEN_AT).records
        assert record.crs_authid is None
        assert record.crs_known is False

    def test_crs_raise_is_unavailable(self) -> None:
        layer = FakeLayer(crs_raise=True)
        (record,) = discover_project(_project(layer), taken_at=TAKEN_AT).records
        assert record.crs_authid is None
        assert record.crs_known is False

    def test_geometry_missing_stays_none(self) -> None:
        layer = FakeLayer(has_geometry_type=False)
        (record,) = discover_project(_project(layer), taken_at=TAKEN_AT).records
        assert record.geometry_type is None

    def test_extent_failure_is_unavailable(self) -> None:
        layer = FakeLayer(has_extent=False)
        (record,) = discover_project(_project(layer), taken_at=TAKEN_AT).records
        assert record.extent is None
        assert record.extent_state == ValueState.UNAVAILABLE
        assert record.extent_unavailable_reason == "no-extent-api"

    def test_nan_extent_is_invalid(self) -> None:
        import math

        layer = FakeLayer(extent=FakeExtent(math.nan, 0.0, 1.0, 1.0))
        (record,) = discover_project(_project(layer), taken_at=TAKEN_AT).records
        assert record.extent is None
        assert record.extent_state == ValueState.UNAVAILABLE
        assert record.extent_unavailable_reason == "extent-invalid"

    def test_fields_failure_is_unavailable(self) -> None:
        layer = FakeLayer(has_fields=False)
        (record,) = discover_project(_project(layer), taken_at=TAKEN_AT).records
        assert record.fields is None
        assert record.fields_state == ValueState.UNAVAILABLE
        assert record.fields_unavailable_reason == "no-fields-api"

    def test_fields_raise_reason(self) -> None:
        layer = FakeLayer(fields_raise=True)
        (record,) = discover_project(_project(layer), taken_at=TAKEN_AT).records
        assert record.fields_state == ValueState.UNAVAILABLE
        assert record.fields_unavailable_reason == "fields-error"

    def test_temporal_absent_is_none(self) -> None:
        layer = FakeLayer(has_temporal=False)
        (record,) = discover_project(_project(layer), taken_at=TAKEN_AT).records
        assert record.has_time is None

    def test_temporal_active(self) -> None:
        layer = FakeLayer(temporal_active=True)
        (record,) = discover_project(_project(layer), taken_at=TAKEN_AT).records
        assert record.has_time is True


@pytest.mark.unit
class TestRedaction:
    def test_credentials_stripped_from_source(self) -> None:
        layer = FakeLayer(source="postgresql://admin:s3cret@db:5432/gis")
        (record,) = discover_project(_project(layer), taken_at=TAKEN_AT).records
        assert "s3cret" not in record.source_redacted
        assert "admin" not in record.source_redacted
        assert "db:5432/gis" in record.source_redacted

    def test_source_failure_is_empty(self) -> None:
        layer = FakeLayer(source_raise=True)
        (record,) = discover_project(_project(layer), taken_at=TAKEN_AT).records
        assert record.source_redacted == ""


@pytest.mark.unit
class TestSnapshotSemantics:
    def test_snapshot_id_deterministic(self) -> None:
        first = discover_project(_project(FakeLayer(layer_id="a")), taken_at=TAKEN_AT)
        second = discover_project(_project(FakeLayer(layer_id="a")), taken_at=TAKEN_AT)
        assert first.snapshot_id == second.snapshot_id
        assert len(first.snapshot_id) == 64

    def test_snapshot_id_changes_with_content(self) -> None:
        first = discover_project(_project(FakeLayer(layer_id="a")), taken_at=TAKEN_AT)
        second = discover_project(_project(FakeLayer(layer_id="b")), taken_at=TAKEN_AT)
        assert first.snapshot_id != second.snapshot_id

    def test_repeated_discovery_structural_equality(self) -> None:
        # Apart from the envelope-only taken_at, repeated discovery is identical.
        layers = lambda: [FakeLayer(layer_id="a"), FakeLayer(layer_id="b")]  # noqa: E731
        first = discover_project(_project(*layers()), taken_at=TAKEN_AT)
        second = discover_project(_project(*layers()), taken_at="2026-03-01T00:00:00+00:00")
        assert first.records == second.records
        assert first.snapshot_id != second.snapshot_id

    def test_dirty_flag(self) -> None:
        clean = discover_project(_project(), taken_at=TAKEN_AT)
        assert clean.project_dirty is False
        dirty = discover_project(_project(dirty=True), taken_at=TAKEN_AT)
        assert dirty.project_dirty is True

    def test_truncation(self) -> None:
        project = _project(*[FakeLayer(layer_id=f"l{i:02d}") for i in range(5)])
        inventory = discover_project(project, taken_at=TAKEN_AT, max_layers=2)
        assert inventory.truncated is True
        assert inventory.total_count == 5
        assert [r.layer_id for r in inventory.records] == ["l00", "l01"]

    def test_default_taken_at_is_iso(self) -> None:
        inventory = discover_project(_project())
        assert "T" in inventory.taken_at


@pytest.mark.unit
class TestDiscoveryBoundary:
    def test_broken_project_yields_empty_snapshot(self) -> None:
        class Broken:
            def mapLayers(self):  # noqa: ANN202
                raise RuntimeError("boom")

        inventory = discover_project(Broken(), taken_at=TAKEN_AT)
        assert inventory.records == ()
        assert inventory.total_count == 0

    def test_unusable_layer_still_recorded(self) -> None:
        class Opaque:
            pass

        project = FakeProject(layers={"": Opaque()})  # type: ignore[dict-item]
        inventory = discover_project(project, taken_at=TAKEN_AT)
        (record,) = inventory.records
        assert record.layer_id == ""
        assert record.valid is False


try:
    from qgis.core import QgsProject  # noqa: F401 — QGIS availability detection only

    HAS_QGIS = True
except ImportError:
    HAS_QGIS = False


@pytest.mark.qgis
@pytest.mark.skipif(not HAS_QGIS, reason="QGIS runtime not available")
class TestDiscoveryQgisRuntime:
    def test_memory_layer_snapshot(self) -> None:
        from qgis.core import QgsVectorLayer

        from lunar_gis.data.discovery_qgis import discover_project as discover

        project = QgsProject.instance()
        layer = QgsVectorLayer("Point?crs=EPSG:4326&field=id:integer", "mem", "memory")
        assert layer.isValid()
        project.addMapLayer(layer)
        try:
            inventory = discover(project, taken_at=TAKEN_AT)
            by_id = {r.layer_id: r for r in inventory.records}
            assert layer.id() in by_id
            record = by_id[layer.id()]
            assert record.provider == "memory"
            assert record.crs_authid == "EPSG:4326"
        finally:
            project.removeMapLayer(layer.id())
