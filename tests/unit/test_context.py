"""Unit tests for ProjectContext using minimal offline fakes."""

import pytest

from lunar_gis.project.context import LayerSummary, ProjectContext
from tests.fixtures.qgis_fakes import FakeCrs, FakeLayer, FakeProject


@pytest.mark.unit
def test_empty_project_returns_empty():
    project = FakeProject(layers={})
    ctx = ProjectContext(project)
    assert ctx.layer_summaries() == []


@pytest.mark.unit
def test_single_vector_layer_all_fields():
    layer = FakeLayer(
        layer_id="id1",
        name="roads",
        provider="ogr",
        geometry_type=1,
        feature_count=42,
        crs_authid="EPSG:4326",
    )
    project = FakeProject(layers={"id1": layer})
    result = ProjectContext(project).layer_summaries()
    assert len(result) == 1
    s = result[0]
    assert s.layer_id == "id1"
    assert s.name == "roads"
    assert s.provider == "ogr"
    assert s.geometry_type == "1"
    assert s.crs_authid == "EPSG:4326"
    assert s.feature_count == 42
    # LayerSummary is frozen
    with pytest.raises(Exception):
        s.name = "x"  # type: ignore[misc]


@pytest.mark.unit
def test_multiple_layers_deterministic_order():
    a = FakeLayer(layer_id="a", name="a", provider="ogr")
    b = FakeLayer(layer_id="b", name="b", provider="postgres")
    # dict insertion order is a, b
    project = FakeProject(layers={"a": a, "b": b})
    names = [s.name for s in ProjectContext(project).layer_summaries()]
    assert names == ["a", "b"]
    # reversed insertion
    project2 = FakeProject(layers={"b": b, "a": a})
    names2 = [s.name for s in ProjectContext(project2).layer_summaries()]
    assert names2 == ["b", "a"]


@pytest.mark.unit
def test_geometry_type_present():
    layer = FakeLayer(geometry_type=2, has_geometry_type=True)
    s = ProjectContext(FakeProject(layers={"1": layer})).layer_summaries()[0]
    assert s.geometry_type == "2"


@pytest.mark.unit
def test_geometry_type_missing_hasattr_false():
    layer = FakeLayer(has_geometry_type=False)
    s = ProjectContext(FakeProject(layers={"1": layer})).layer_summaries()[0]
    assert s.geometry_type is None


@pytest.mark.unit
def test_geometry_type_raises_returns_none():
    layer = FakeLayer(has_geometry_type=True, geometry_raise=True)
    s = ProjectContext(FakeProject(layers={"1": layer})).layer_summaries()[0]
    assert s.geometry_type is None


@pytest.mark.unit
def test_feature_count_present():
    layer = FakeLayer(feature_count=7, has_feature_count=True)
    s = ProjectContext(FakeProject(layers={"1": layer})).layer_summaries()[0]
    assert s.feature_count == 7


@pytest.mark.unit
def test_feature_count_missing_hasattr_false():
    layer = FakeLayer(has_feature_count=False)
    s = ProjectContext(FakeProject(layers={"1": layer})).layer_summaries()[0]
    assert s.feature_count is None


@pytest.mark.unit
def test_feature_count_raises_returns_none():
    layer = FakeLayer(has_feature_count=True, feature_raise=True)
    s = ProjectContext(FakeProject(layers={"1": layer})).layer_summaries()[0]
    assert s.feature_count is None


@pytest.mark.unit
def test_feature_count_int_coercion():
    # featureCount may return string-like int; ProjectContext does int()
    layer = FakeLayer(feature_count="3", has_feature_count=True)  # type: ignore[arg-type]
    s = ProjectContext(FakeProject(layers={"1": layer})).layer_summaries()[0]
    assert s.feature_count == 3


@pytest.mark.unit
def test_crs_authid_present():
    layer = FakeLayer(crs_authid="EPSG:3857")
    s = ProjectContext(FakeProject(layers={"1": layer})).layer_summaries()[0]
    assert s.crs_authid == "EPSG:3857"


@pytest.mark.unit
def test_crs_authid_empty_string():
    # QGIS may return "" for invalid CRS; current code stores "" (not None) — verify behavior
    layer = FakeLayer(crs_authid="")
    s = ProjectContext(FakeProject(layers={"1": layer})).layer_summaries()[0]
    assert s.crs_authid == ""


@pytest.mark.unit
def test_crs_authid_missing_returns_none():
    # Simulate layer.crs() raising
    layer = FakeLayer(crs_raise=True)
    s = ProjectContext(FakeProject(layers={"1": layer})).layer_summaries()[0]
    assert s.crs_authid is None


@pytest.mark.unit
def test_crs_authid_raise_via_crs_object():
    # Simulate crs().authid() raising
    layer = FakeLayer()
    # monkeypatch crs to return raising FakeCrs
    layer.crs = lambda: FakeCrs(authid="EPSG:4326", raise_exc=True)  # type: ignore[method-assign]
    s = ProjectContext(FakeProject(layers={"1": layer})).layer_summaries()[0]
    assert s.crs_authid is None


@pytest.mark.unit
def test_layer_summary_fields_with_raster_like_missing_optional():
    # Raster-like: no geometryType/featureCount, but provider and crs present
    layer = FakeLayer(
        has_geometry_type=False,
        has_feature_count=False,
        provider="gdal",
        crs_authid="EPSG:4326",
    )
    s = ProjectContext(FakeProject(layers={"1": layer})).layer_summaries()[0]
    assert s.geometry_type is None
    assert s.feature_count is None
    assert s.provider == "gdal"
    assert s.crs_authid == "EPSG:4326"


@pytest.mark.unit
def test_layer_summary_is_frozen_and_equality():
    a = LayerSummary(layer_id="x", name="n", provider="ogr")
    b = LayerSummary(layer_id="x", name="n", provider="ogr")
    assert a == b
    assert hash(a) == hash(b)


@pytest.mark.unit
def test_project_context_preserves_provider_and_name():
    layer = FakeLayer(name="my roads", provider="wfs")
    s = ProjectContext(FakeProject(layers={"1": layer})).layer_summaries()[0]
    assert s.name == "my roads"
    assert s.provider == "wfs"
