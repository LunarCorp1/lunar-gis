"""Unit tests for M4-T04 deterministic transformation boundary.

QGIS-free contract/validation/tool tests run offline. Processing
algorithm loading is marked qgis (existing convention).
"""

from __future__ import annotations

import pytest

from lunar_gis.agent.registry import ToolRegistry
from lunar_gis.data import transforms as transforms_module
from lunar_gis.data.transform_tools import (
    RUN_TRANSFORMATION_TOOL_SPEC,
    register_transformation_tool,
    run_transformation_handler,
)
from lunar_gis.data.transforms import (
    EXECUTOR_PINS,
    FilterPredicate,
    TransformOp,
    chain_identity,
    is_preserving,
    make_step,
    requires_derived_provenance,
    validate_chain,
    validate_filter_predicate,
    validate_step,
)


class TestOpSet:
    def test_closed_seven_ops(self) -> None:
        assert {op.value for op in TransformOp} == {
            "reproject-vector",
            "reproject-raster",
            "clip",
            "filter",
            "join",
            "raster-to-vector",
            "vector-to-raster",
        }

    def test_no_merge_op(self) -> None:
        assert "merge" not in {op.value for op in TransformOp}

    def test_preserving_transforming_split(self) -> None:
        assert is_preserving("reproject-vector")
        assert is_preserving("clip")
        assert is_preserving("filter")
        assert not is_preserving("join")
        assert requires_derived_provenance("join")
        assert requires_derived_provenance("raster-to-vector")
        assert requires_derived_provenance("vector-to-raster")
        assert requires_derived_provenance("reproject-raster")

    def test_executor_pins_cover_all_ops(self) -> None:
        for op in TransformOp:
            assert op.value in EXECUTOR_PINS
            alg_id, version = EXECUTOR_PINS[op.value]
            assert alg_id and version


class TestFilterPredicate:
    def test_simple_equality(self) -> None:
        assert FilterPredicate(field="pop", op="=", value="100").to_expression() == '"pop" = 100'

    def test_string_quoting(self) -> None:
        assert FilterPredicate(field="name", op="=", value="O'Brien").to_expression() == ("\"name\" = 'O''Brien'")

    def test_field_quote_doubling(self) -> None:
        assert FilterPredicate(field='we"ird', op="=", value="1").to_expression() == '"we""ird" = 1'

    def test_is_null(self) -> None:
        assert FilterPredicate(field="x", op="IS NULL").to_expression() == '"x" IS NULL'

    def test_in_list(self) -> None:
        expr = FilterPredicate(field="code", op="IN", value="a, 1").to_expression()
        assert expr == "\"code\" IN ('a', 1)"

    def test_like(self) -> None:
        assert FilterPredicate(field="n", op="LIKE", value="A%").to_expression() == "\"n\" LIKE 'A%'"

    def test_bad_operator_raises(self) -> None:
        with pytest.raises(ValueError):
            FilterPredicate(field="x", op="DROP TABLE").to_expression()

    def test_validate_predicate(self) -> None:
        assert validate_filter_predicate({"field": "a", "op": "="}) == []
        assert validate_filter_predicate({"field": "a"}) != []
        assert validate_filter_predicate({"field": "a", "op": "??"}) != []
        assert validate_filter_predicate("nope") != []


class TestValidateStep:
    def test_valid_reproject(self) -> None:
        assert validate_step("reproject-vector", {"target_crs": "EPSG:3857"}, ("lid",)) == []

    def test_unknown_op(self) -> None:
        assert validate_step("merge", {}, ("lid",)) != []

    def test_missing_required_param(self) -> None:
        assert validate_step("reproject-vector", {}, ("lid",)) != []

    def test_unexpected_param(self) -> None:
        assert validate_step("reproject-vector", {"target_crs": "EPSG:3857", "nope": 1}, ("lid",)) != []

    def test_empty_input_refs(self) -> None:
        assert validate_step("reproject-vector", {"target_crs": "EPSG:3857"}, ()) != []

    def test_join_rejects_many(self) -> None:
        params = {"join_layer_id": "b", "join_field": "id", "target_field": "id", "join_type": "one-to-many"}
        assert validate_step("join", params, ("a",)) != []

    def test_join_accepts_one_to_one(self) -> None:
        params = {"join_layer_id": "b", "join_field": "id", "target_field": "id"}
        assert validate_step("join", params, ("a",)) == []

    def test_filter_bad_operator(self) -> None:
        assert validate_step("filter", {"field": "a", "op": "??"}, ("lid",)) != []


class TestValidateChain:
    def test_empty_chain(self) -> None:
        assert validate_chain([]) != []

    def test_too_long(self) -> None:
        step = {"op": "clip", "params": {"overlay_layer_id": "b"}, "input_refs": ["a"]}
        assert validate_chain([step] * 4) != []

    def test_valid_chain(self) -> None:
        step = {"op": "clip", "params": {"overlay_layer_id": "b"}, "input_refs": ["a"]}
        assert validate_chain([step]) == []

    def test_bad_step_indexed(self) -> None:
        errors = validate_chain([{"op": "nope", "params": {}, "input_refs": []}])
        assert any("chain[0]" in e for e in errors)


class TestMakeStep:
    def test_make_step_pins_executor(self) -> None:
        step = make_step("reproject-vector", {"target_crs": "EPSG:3857"}, ("a",), "out.gpkg")
        assert "native:reprojectlayer" in step.op_version
        assert step.executor == "qgis-processing"
        assert step.param_map() == {"target_crs": "EPSG:3857"}

    def test_make_step_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            make_step("reproject-vector", {}, ("a",), "out")

    def test_chain_identity_deterministic(self) -> None:
        s1 = make_step("clip", {"overlay_layer_id": "b"}, ("a",), "out")
        s2 = make_step("clip", {"overlay_layer_id": "b"}, ("a",), "out")
        assert chain_identity((s1,)) == chain_identity((s2,))
        s3 = make_step("clip", {"overlay_layer_id": "c"}, ("a",), "out")
        assert chain_identity((s1,)) != chain_identity((s3,))


class TestTool:
    def test_spec_is_high_risk(self) -> None:
        assert RUN_TRANSFORMATION_TOOL_SPEC.risk.value == "high"
        assert RUN_TRANSFORMATION_TOOL_SPEC.name == "data.run_transformation"

    def test_register(self) -> None:
        registry = ToolRegistry()
        register_transformation_tool(registry)
        assert registry.has("data.run_transformation")

    def test_handler_rejects_non_list(self) -> None:
        result = run_transformation_handler({"steps": "nope"})
        assert result["ok"] is False

    def test_handler_rejects_invalid_chain(self) -> None:
        result = run_transformation_handler({"steps": [{"op": "nope"}]})
        assert result["ok"] is False
        assert "invalid chain" in result["error"]

    def test_handler_without_qgis_fails_closed(self) -> None:
        pytest.importorskip("qgis", reason="QGIS runtime required for execution path")
        result = run_transformation_handler(
            {"steps": [{"op": "clip", "params": {"overlay_layer_id": "b"}, "input_refs": ["a"]}]}
        )
        assert result["ok"] is False


class TestImportBoundary:
    def test_no_qgis_import_in_contracts(self) -> None:
        import pathlib

        text = pathlib.Path(transforms_module.__file__).read_text(encoding="utf-8")
        assert "import qgis" not in text
        assert "from qgis" not in text

    def test_no_forbidden_calls_in_contracts(self) -> None:
        import pathlib

        text = pathlib.Path(transforms_module.__file__).read_text(encoding="utf-8")
        for banned in ("eval(", "exec(", "subprocess", "pickle", "socket", "urllib", "requests"):
            assert banned not in text


@pytest.mark.qgis
class TestProcessingAlgorithms:
    def test_provider_loads_all_algorithms(self) -> None:
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
        } <= names
