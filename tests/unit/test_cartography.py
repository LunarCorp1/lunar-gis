"""Unit tests for M7 deterministic cartography."""

from __future__ import annotations

import pytest

from lunar_gis.agent.registry import ToolRegistry
from lunar_gis.cartography import layout_qgis as layout_module
from lunar_gis.cartography import styles as styles_module
from lunar_gis.cartography.cartography_tools import (
    create_layout_handler,
    export_map_handler,
    register_cartography_tools,
    style_layer_handler,
)
from lunar_gis.cartography.styles import (
    ClassificationMethod,
    GeometryFamily,
    StyleRule,
    compute_breaks,
    default_style_for_geometry,
    palette_for_classes,
    validate_style_rule,
)


class TestPalette:
    def test_okabe_ito_order(self) -> None:
        colors = palette_for_classes(3)
        assert colors == ("#0072B2", "#E69F00", "#009E73")

    def test_count_bounds(self) -> None:
        with pytest.raises(ValueError):
            palette_for_classes(0)
        with pytest.raises(ValueError):
            palette_for_classes(99)


class TestBreaks:
    def test_equal_interval(self) -> None:
        breaks = compute_breaks([0.0, 10.0], ClassificationMethod.EQUAL_INTERVAL, 2)
        assert breaks == [5.0, 10.0]

    def test_quantile(self) -> None:
        breaks = compute_breaks([1.0, 2.0, 3.0, 4.0], ClassificationMethod.QUANTILE, 2)
        assert len(breaks) == 2
        assert breaks[0] < breaks[1]

    def test_constant(self) -> None:
        assert compute_breaks([5.0, 5.0], ClassificationMethod.EQUAL_INTERVAL, 3) == [5.0, 5.0, 5.0]

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            compute_breaks([], ClassificationMethod.EQUAL_INTERVAL, 2)

    def test_unsupported_method(self) -> None:
        with pytest.raises(ValueError):
            compute_breaks([1.0, 2.0], ClassificationMethod.SINGLE_SYMBOL, 2)


class TestStyleRule:
    def test_default(self) -> None:
        rule = default_style_for_geometry("Point")
        assert rule.method == ClassificationMethod.SINGLE_SYMBOL

    def test_unknown_geometry_falls_back(self) -> None:
        assert default_style_for_geometry("Mesh").geometry == GeometryFamily.POINT

    def test_categorized_requires_field(self) -> None:
        with pytest.raises(ValueError):
            StyleRule(geometry=GeometryFamily.POINT, method=ClassificationMethod.CATEGORIZED)

    def test_validate(self) -> None:
        assert validate_style_rule({"geometry": "Point", "method": "single-symbol"}) == []
        assert validate_style_rule({"method": "nope"}) != []
        assert validate_style_rule({"method": "categorized"}) != []
        assert validate_style_rule({"geometry": "Point", "method": "equal-interval", "field": "x", "classes": 4}) == []


class TestToolsOffline:
    def test_all_fail_closed(self) -> None:
        assert style_layer_handler({"layer_id": "a"})["ok"] is False
        assert create_layout_handler({"title": "t", "layer_ids": ["a"]})["ok"] is False
        assert export_map_handler({"layout_name": "l", "output_relpath": "m.pdf"})["ok"] is False

    def test_export_requires_workspace(self) -> None:
        result = export_map_handler({"layout_name": "l", "output_relpath": "../../evil.pdf"})
        assert result["ok"] is False

    def test_register(self) -> None:
        registry = ToolRegistry()
        register_cartography_tools(registry)
        assert registry.has("cartography.style_layer")
        assert registry.has("cartography.create_layout")
        assert registry.has("cartography.export_map")


class TestImportBoundary:
    def test_styles_qgis_free(self) -> None:
        import pathlib

        text = pathlib.Path(styles_module.__file__).read_text(encoding="utf-8")
        assert "import qgis" not in text
        assert "from qgis" not in text

    def test_layout_deferred_only(self) -> None:
        import pathlib

        text = pathlib.Path(layout_module.__file__).read_text(encoding="utf-8")
        for line in text.splitlines():
            if line and not line[0].isspace():
                assert not line.strip().startswith("import qgis")
                assert not line.strip().startswith("from qgis")


@pytest.mark.qgis
class TestLiveCartography:
    def test_style_and_layout(self) -> None:
        qgis_core = pytest.importorskip("qgis.core")
        from lunar_gis.cartography.layout_qgis import apply_style, create_layout, qa_layout

        _ = qgis_core
        from qgis.core import QgsProject, QgsVectorLayer  # type: ignore[import-not-found]

        project = QgsProject.instance()
        layer = QgsVectorLayer("Point?crs=EPSG:4326&field=id:integer", "c_pts", "memory")
        assert layer.isValid()
        project.addMapLayer(layer)
        try:
            styled = apply_style(layer, default_style_for_geometry("Point"))
            assert styled["ok"] is True
            built = create_layout(project, "Test Map", [layer.id()], provenance_text="test provenance")
            assert built["ok"] is True, built
            assert built["qa"]["ok"] is True
            assert qa_layout(None)["ok"] is False
        finally:
            project.removeMapLayer(layer.id())
