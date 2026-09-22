"""Unit tests for the deterministic suitability (WLC) engine + tool."""

from __future__ import annotations

import pytest

from lunar_gis.agent.registry import ToolRegistry
from lunar_gis.analysis import suitability as suitability_module
from lunar_gis.analysis.suitability import (
    Direction,
    SuitabilityCriterion,
    suitability_wlc,
)
from lunar_gis.analysis.suitability_tools import (
    SUITABILITY_TOOL_SPEC,
    parse_criteria,
    register_suitability_tool,
    suitability_handler,
)


def _criteria() -> list[SuitabilityCriterion]:
    return [
        SuitabilityCriterion(field="pop", weight=0.6, direction=Direction.BENEFIT),
        SuitabilityCriterion(field="dist", weight=0.4, direction=Direction.COST),
    ]


def _units() -> list[dict]:
    return [
        {"pop": 100.0, "dist": 9.0},
        {"pop": 200.0, "dist": 5.0},
        {"pop": 300.0, "dist": 1.0},
    ]


class TestEngine:
    def test_scores_ranked(self) -> None:
        result = suitability_wlc(_units(), _criteria())
        assert [u.key for u in result.scores] == [2, 1, 0]
        assert result.scores[0].score == pytest.approx(1.0)
        assert result.scores[-1].score == pytest.approx(0.0)
        assert result.statistics["count"] == 3
        assert result.excluded_nulls == 0
        assert result.method == "wlc-minmax"

    def test_cost_direction(self) -> None:
        result = suitability_wlc(
            [{"x": 1.0}, {"x": 9.0}],
            [SuitabilityCriterion(field="x", weight=1.0, direction=Direction.COST)],
        )
        assert result.scores[0].key == 0  # lower x wins under COST

    def test_classes(self) -> None:
        result = suitability_wlc(_units(), _criteria())
        assert result.scores[0].suitability_class == "Very high"
        assert result.scores[-1].suitability_class == "Very low"
        assert sum(result.statistics["class_counts"].values()) == 3

    def test_nulls_excluded(self) -> None:
        units = _units() + [{"pop": None, "dist": 2.0}]
        result = suitability_wlc(units, _criteria())
        assert result.excluded_nulls == 1
        assert result.statistics["count"] == 3

    def test_weights_must_sum_to_one(self) -> None:
        with pytest.raises(ValueError):
            suitability_wlc(_units(), [SuitabilityCriterion(field="pop", weight=0.5, direction=Direction.BENEFIT)])

    def test_constant_field_rejected(self) -> None:
        with pytest.raises(ValueError):
            suitability_wlc(
                [{"x": 5.0}, {"x": 5.0}],
                [SuitabilityCriterion(field="x", weight=1.0, direction=Direction.BENEFIT)],
            )

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValueError):
            suitability_wlc([], _criteria())
        with pytest.raises(ValueError):
            suitability_wlc(_units(), [])

    def test_deterministic_identity(self) -> None:
        first = suitability_wlc(_units(), _criteria())
        second = suitability_wlc(_units(), _criteria())
        assert first.input_hash == second.input_hash
        assert [u.score for u in first.scores] == [u.score for u in second.scores]


class TestParseCriteria:
    def test_valid(self) -> None:
        parsed = parse_criteria([{"field": "a", "weight": 1.0, "direction": "cost"}])
        assert parsed[0].direction == Direction.COST

    def test_bad_direction(self) -> None:
        with pytest.raises(ValueError):
            parse_criteria([{"field": "a", "weight": 1.0, "direction": "sideways"}])

    def test_missing_field(self) -> None:
        with pytest.raises(ValueError):
            parse_criteria([{"weight": 1.0}])


class TestTool:
    def test_spec_low_risk(self) -> None:
        assert SUITABILITY_TOOL_SPEC.risk.value == "low"
        assert SUITABILITY_TOOL_SPEC.name == "analysis.suitability"

    def test_register(self) -> None:
        registry = ToolRegistry()
        register_suitability_tool(registry)
        assert registry.has("analysis.suitability")

    def test_offline_fail_closed(self) -> None:
        result = suitability_handler({"layer_id": "a", "criteria": []})
        assert result["ok"] is False

    def test_bad_criteria_offline(self) -> None:
        # without QGIS this fails closed before criteria parsing; with QGIS
        # the criteria error surfaces — either way ok is False
        result = suitability_handler({"layer_id": "a", "criteria": [{"field": "x"}]})
        assert result["ok"] is False


class TestImportBoundary:
    def test_engine_qgis_free(self) -> None:
        import pathlib

        text = pathlib.Path(suitability_module.__file__).read_text(encoding="utf-8")
        assert "import qgis" not in text
        assert "from qgis" not in text


@pytest.mark.qgis
class TestLiveSuitability:
    def test_memory_layer_scoring(self) -> None:
        pytest.importorskip("qgis.core")
        from qgis.core import QgsFeature, QgsProject, QgsVectorLayer  # type: ignore[import-not-found]

        from lunar_gis.analysis.suitability_tools import suitability_handler

        project = QgsProject.instance()
        layer = QgsVectorLayer("Point?crs=EPSG:4326&field=pop:integer&field=dist:double", "suit", "memory")
        assert layer.isValid()
        layer.startEditing()
        for pop, dist in ((100, 1.0), (200, 5.0), (300, 9.0)):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([pop, dist])
            assert layer.addFeature(feature)
        assert layer.commitChanges()
        project.addMapLayer(layer)
        try:
            result = suitability_handler(
                {
                    "layer_id": layer.id(),
                    "criteria": [
                        {"field": "pop", "weight": 0.6, "direction": "benefit"},
                        {"field": "dist", "weight": 0.4, "direction": "cost"},
                    ],
                }
            )
            assert result["ok"] is True, result
            assert result["scored_count"] == 3
        finally:
            project.removeMapLayer(layer.id())
