"""Unit tests for M4-T07 fulfillment planning + data tools."""

from __future__ import annotations

import pytest

from lunar_gis.agent.registry import ToolRegistry
from lunar_gis.data import fulfillment as fulfillment_module
from lunar_gis.data.contracts import AvailabilityState
from lunar_gis.data.data_tools import (
    check_requirement_handler,
    describe_project_handler,
    register_data_tools,
    register_local_file_handler,
    validate_dataset_handler,
)
from lunar_gis.data.discovery_qgis import discover_project
from lunar_gis.data.fulfillment import (
    FulfillmentKind,
    make_data_result,
    plan_from_dicts,
)
from tests.fixtures.qgis_fakes import (
    FakeExtent,
    FakeFeature,
    FakeFields,
    FakeField,
    FakeGeometry,
    FakeLayer,
    FakeProject,
)

TAKEN_AT = "2026-04-01T00:00:00+00:00"


def _layer(layer_id: str = "a") -> FakeLayer:
    features = [FakeFeature(fid=i + 1, attributes={"id": i + 1}, geometry=FakeGeometry(valid=True)) for i in range(3)]
    return FakeLayer(
        layer_id=layer_id,
        name=layer_id,
        provider="ogr",
        geometry_type=0,
        feature_count=3,
        crs_authid="EPSG:4326",
        extent=FakeExtent(0.0, 0.0, 10.0, 10.0),
        fields=FakeFields([FakeField("id", "Int")]),
        is_valid=True,
        source="/data/x.gpkg",
        features=features,
    )


def _inventory() -> object:
    return discover_project(FakeProject(layers={"a": _layer("a")}), taken_at=TAKEN_AT)


def _requirement(**overrides) -> dict:
    base: dict = {"name": "req", "geometry": "Point", "required_fields": ["id"]}
    base.update(overrides)
    return base


class TestPlanFulfillment:
    def test_available_local_layer(self) -> None:
        plan = plan_from_dicts(_requirement(), _inventory())
        assert plan.availability == AvailabilityState.AVAILABLE
        assert plan.kind == FulfillmentKind.LOCAL_LAYER
        assert plan.layer_id == "a"

    def test_derivable_chain(self) -> None:
        plan = plan_from_dicts(_requirement(crs={"authid": "EPSG:3857"}), _inventory())
        assert plan.availability == AvailabilityState.DERIVABLE
        assert plan.kind == FulfillmentKind.DERIVATION_CHAIN
        assert len(plan.chain) >= 1

    def test_missing_schema_gap(self) -> None:
        plan = plan_from_dicts(_requirement(required_fields=["nope"]), _inventory())
        assert plan.availability == AvailabilityState.MISSING
        assert plan.kind == FulfillmentKind.MISSING
        assert plan.missing_reason == "schema-gap"

    def test_missing_with_provider_proposal(self) -> None:
        req = _requirement(
            required_fields=["nope"],
            acceptable_sources=["local-project", "provider:stac.earth-search"],
        )
        plan = plan_from_dicts(req, _inventory())
        assert plan.availability == AvailabilityState.MISSING
        assert plan.kind == FulfillmentKind.PROVIDER_PROPOSAL
        assert plan.provider_id == "stac.earth-search"
        assert plan.missing_reason == "schema-gap"

    def test_deterministic(self) -> None:
        first = plan_from_dicts(_requirement(), _inventory())
        second = plan_from_dicts(_requirement(), _inventory())
        assert first == second

    def test_invalid_requirement_raises(self) -> None:
        with pytest.raises(ValueError):
            plan_from_dicts({"name": "bad", "geometry": "Nope"}, _inventory())


class TestDataResult:
    def test_make_result(self) -> None:
        result = make_data_result(
            requirement_name="req",
            availability=AvailabilityState.AVAILABLE,
            subject_kind="layer-ref",
            subject_ref="a",
            validation_verdict="VALID",
            satisfaction="satisfied",
        )
        assert result.requirement_name == "req"
        assert result.fulfillment_version == "1.0"


class TestCheckRequirementTool:
    def test_available(self) -> None:
        from lunar_gis.data.data_tools import _inventory_to_dict

        inventory_payload = _inventory_to_dict(_inventory())
        assert inventory_payload["ok"] is True
        result = check_requirement_handler({"requirement": _requirement(), "inventory": inventory_payload})
        assert result["ok"] is True
        assert result["availability"] == "available"
        assert result["fulfillment_kind"] == "local-layer"

    def test_invalid_requirement(self) -> None:
        result = check_requirement_handler({"requirement": {"name": "x", "geometry": "Nope"}})
        assert result["ok"] is False

    def test_no_inventory_no_qgis(self) -> None:
        result = check_requirement_handler({"requirement": _requirement()})
        # offline: no QGIS runtime → fail-closed
        assert result["ok"] is False


class TestDescribeTool:
    def test_without_qgis_fails_closed(self) -> None:
        result = describe_project_handler({})
        assert result["ok"] is False
        assert result["error"] == "qgis-runtime-unavailable"

    def test_inventory_dict_duck_typed(self) -> None:
        """Regression: _inventory_to_dict must not rely on module identity.

        Import-guard tests reload lunar_gis.data.contracts mid-session,
        creating a second LayerInventory class object; isinstance checks
        across the reload boundary fail. The snapshot shape is the contract.
        """
        import types

        from lunar_gis.data.data_tools import _inventory_to_dict

        fake = types.SimpleNamespace(records=[], snapshot_id="s", taken_at="t", project_dirty=False)
        fake.total_count = 0
        fake.truncated = False
        payload = _inventory_to_dict(fake)
        assert payload["ok"] is True
        assert payload["snapshot_id"] == "s"

    def test_inventory_dict_rejects_garbage(self) -> None:
        from lunar_gis.data.data_tools import _inventory_to_dict

        assert _inventory_to_dict(object())["ok"] is False
        assert _inventory_to_dict(None)["ok"] is False


class TestValidateTool:
    def test_bad_subject_kind(self) -> None:
        result = validate_dataset_handler({"subject_kind": "nope", "subject_ref": "x"})
        assert result["ok"] is False

    def test_missing_file(self, tmp_path) -> None:
        result = validate_dataset_handler({"subject_kind": "file", "subject_ref": str(tmp_path / "missing.gpkg")})
        assert result["ok"] is False or result.get("verdict") == "invalid"

    def test_layer_without_qgis(self) -> None:
        result = validate_dataset_handler({"subject_kind": "layer-ref", "subject_ref": "a"})
        assert result["ok"] is False


class TestRegisterTool:
    def test_traversal_rejected(self) -> None:
        result = register_local_file_handler({"sandbox_relpath": "../../evil.gpkg"})
        assert result["ok"] is False

    def test_valid_registration(self, tmp_path) -> None:
        target = tmp_path / "data.gpkg"
        target.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
        result = register_local_file_handler({"sandbox_relpath": "data.gpkg", "workspace_dir": str(tmp_path)})
        assert result["ok"] is True
        assert result["provenance_ref"]
        assert result["sandbox_relpath"] == "data.gpkg"

    def test_missing_file_rejected(self, tmp_path) -> None:
        result = register_local_file_handler({"sandbox_relpath": "ghost.gpkg", "workspace_dir": str(tmp_path)})
        assert result["ok"] is False

    def test_register_tools(self) -> None:
        registry = ToolRegistry()
        register_data_tools(registry)
        for name in (
            "data.describe_project",
            "data.check_requirement",
            "data.validate_dataset",
            "data.register_local_file",
            "data.load_into_project",
        ):
            assert registry.has(name)

    def test_load_rejects_bad_sandbox(self) -> None:
        from lunar_gis.data.data_tools import load_into_project_handler

        assert load_into_project_handler({"sandbox_dir": "/nope", "sandbox_relpath": "a.gpkg"})["ok"] is False
        assert load_into_project_handler({"sandbox_dir": "/tmp", "sandbox_relpath": "../../evil.gpkg"})["ok"] is False

    def test_load_rejects_executable_offline(self, tmp_path) -> None:
        from lunar_gis.data.data_tools import load_into_project_handler

        target = tmp_path / "run.exe"
        target.write_bytes(b"MZ" + b"\x00" * 100)
        result = load_into_project_handler({"sandbox_dir": str(tmp_path), "sandbox_relpath": "run.exe"})
        assert result["ok"] is False
        assert "suffix" in result["error"]

    def test_load_without_qgis_fails_closed(self, tmp_path) -> None:
        from lunar_gis.data.data_tools import load_into_project_handler

        target = tmp_path / "data.geojson"
        target.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
        result = load_into_project_handler({"sandbox_dir": str(tmp_path), "sandbox_relpath": "data.geojson"})
        assert result["ok"] is False
        assert result["error"] == "qgis-runtime-unavailable"


class TestImportBoundary:
    def test_fulfillment_qgis_free(self) -> None:
        import pathlib

        text = pathlib.Path(fulfillment_module.__file__).read_text(encoding="utf-8")
        assert "import qgis" not in text
