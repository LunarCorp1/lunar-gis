"""Unit tests for M6 governed GIS analysis tools."""

from __future__ import annotations

import pytest

from lunar_gis.agent.registry import ToolRegistry
from lunar_gis.analysis import gis_tools as gis_tools_module
from lunar_gis.analysis.gis_tools import (
    GIS_TOOL_SPECS,
    buffer_handler,
    dissolve_handler,
    intersection_handler,
    register_gis_tools,
    spatial_join_handler,
    zonal_statistics_handler,
)


class TestSpecs:
    def test_five_tools_all_low(self) -> None:
        names = {spec.name for spec in GIS_TOOL_SPECS}
        assert names == {
            "analysis.buffer",
            "analysis.intersection",
            "analysis.dissolve",
            "analysis.zonal_statistics",
            "analysis.spatial_join",
        }
        for spec in GIS_TOOL_SPECS:
            assert spec.risk.value == "low"

    def test_register(self) -> None:
        registry = ToolRegistry()
        register_gis_tools(registry)
        for spec in GIS_TOOL_SPECS:
            assert registry.has(spec.name)


class TestHandlersOffline:
    def test_all_fail_closed_without_qgis(self) -> None:
        assert buffer_handler({"layer_id": "a", "distance": 10})["ok"] is False
        assert intersection_handler({"layer_id": "a", "overlay_layer_id": "b"})["ok"] is False
        assert dissolve_handler({"layer_id": "a"})["ok"] is False
        assert zonal_statistics_handler({"layer_id": "a", "raster_layer_id": "r"})["ok"] is False
        assert spatial_join_handler({"layer_id": "a", "join_layer_id": "b"})["ok"] is False

    def test_spatial_join_bad_predicate_offline(self) -> None:
        # predicate validation happens after project resolution; offline → qgis error
        result = spatial_join_handler({"layer_id": "a", "join_layer_id": "b", "predicate": "nope"})
        assert result["ok"] is False


class TestImportBoundary:
    def test_no_top_level_qgis_or_forbidden(self) -> None:
        import pathlib

        text = pathlib.Path(gis_tools_module.__file__).read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            # Deferred (indented, function-level) qgis imports are allowed;
            # top-level qgis imports would break offline importability.
            if line and not line[0].isspace():
                assert not stripped.startswith("import qgis")
                assert not stripped.startswith("from qgis")
        for banned in ("subprocess", "pickle"):
            assert banned not in text


@pytest.mark.qgis
class TestProviderLoadsGis:
    def test_all_fourteen_algorithms(self) -> None:
        pytest.importorskip("qgis.core")
        from lunar_gis.processing.provider import LunarGISProvider

        provider = LunarGISProvider()
        provider.loadAlgorithms()
        names = {alg.name() for alg in provider.algorithms()}
        assert {
            "ahp_pairwise",
            "ahp_sensitivity",
            "reproject_vector",
            "reproject_raster",
            "clip_layer",
            "filter_features",
            "join_attributes",
            "raster_to_vector",
            "vector_to_raster",
            "gis_buffer",
            "gis_intersection",
            "gis_dissolve",
            "gis_zonal_statistics",
            "gis_spatial_join",
            "gis_suitability",
        } <= names
