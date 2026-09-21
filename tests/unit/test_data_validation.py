"""Unit tests for M4-T03 deterministic local validation.

QGIS-free contract/shape/satisfaction tests run offline. QGIS-specific
validation runs against duck-typed fakes offline; live-runtime tests are
marked qgis and skip without QGIS (existing convention).
"""

from __future__ import annotations

import json

import pytest

from lunar_gis.data import validation_qgis as validation_module
from lunar_gis.data.contracts import (
    DataRequirement,
    LayerExtent,
    LayerRecord,
    SatisfactionState,
    ValidationReport,
    ValidationVerdict,
    ValueState,
    evaluate_join_values,
    parse_requirement,
    report_canonical_json,
    report_identity,
    satisfy_requirement,
)
from lunar_gis.data.discovery_qgis import discover_project
from lunar_gis.data.validation_qgis import (
    check_magic,
    check_suffix,
    validate_join_key,
    validate_local_file,
    validate_project_layer,
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


def _layer(
    layer_id: str = "a",
    *,
    n_features: int = 3,
    valid_geometry: bool = True,
    fields: FakeFields | None = None,
    crs_authid: str | None = "EPSG:4326",
    is_valid: bool = True,
    attrs: dict | None = None,
) -> FakeLayer:
    features = [
        FakeFeature(
            fid=i + 1,
            attributes=attrs or {"id": i + 1, "name": f"n{i + 1}"},
            geometry=FakeGeometry(valid=valid_geometry),
        )
        for i in range(n_features)
    ]
    return FakeLayer(
        layer_id=layer_id,
        name=layer_id,
        provider="ogr",
        geometry_type=0,
        feature_count=n_features,
        crs_authid=crs_authid if crs_authid is not None else "",
        extent=FakeExtent(0.0, 0.0, 10.0, 10.0),
        fields=fields if fields is not None else FakeFields([FakeField("id", "Int"), FakeField("name", "String")]),
        is_valid=is_valid,
        source="/data/x.gpkg",
        features=features,
    )


def _record(layer_id: str = "a") -> LayerRecord:
    (record,) = discover_project(FakeProject(layers={layer_id: _layer(layer_id)}), taken_at=TAKEN_AT).records
    return record


def _report(**overrides) -> ValidationReport:
    fields = {
        "subject_kind": "layer-ref",
        "subject_ref": "a",
        "requirement_name": "req",
        "snapshot_id": "snap",
        "verdict": ValidationVerdict.VALID,
        "checks": (),
        "crs_authid": "EPSG:4326",
        "crs_known": True,
        "geometry_canonical": "Point",
        "field_list": (("id", "Int"),),
        "extent": LayerExtent(0.0, 0.0, 10.0, 10.0, "EPSG:4326"),
        "fields_state": ValueState.KNOWN,
        "feature_count": 3,
        "feature_count_state": ValueState.KNOWN,
        "validity": "FULL",
        "validity_sample": (3, 3),
        "coverage_met": True,
        "coverage_method": "transformed-bbox-containment",
        "has_time": False,
        "warnings": (),
    }
    fields.update(overrides)
    return ValidationReport(**fields)  # type: ignore[arg-type]


def _req(**overrides) -> DataRequirement:
    payload: dict = {"name": "req"}
    payload.update(overrides)
    return parse_requirement(payload)


# ===========================================================================
# Contract shapes
# ===========================================================================


@pytest.mark.unit
class TestValidationShapes:
    def test_verdict_enum_exact(self) -> None:
        assert [v.value for v in ValidationVerdict] == ["valid", "empty", "invalid"]

    def test_satisfaction_enum_exact(self) -> None:
        assert [s.value for s in SatisfactionState] == [
            "satisfied",
            "not-satisfied",
            "unknown-deferred",
            "partial",
        ]

    def test_report_frozen_and_version(self) -> None:
        report = _report()
        assert report.validation_version == "1.0"
        with pytest.raises(Exception):
            report.verdict = ValidationVerdict.INVALID  # type: ignore[misc]

    def test_report_serialization_deterministic(self) -> None:
        first = report_canonical_json(_report())
        second = report_canonical_json(_report())
        assert first == second
        payload = json.loads(first)
        assert list(payload.keys()) == sorted(payload.keys())
        assert report_identity(_report()) == report_identity(_report())
        assert len(report_identity(_report())) == 64

    def test_join_key_report_shapes(self) -> None:
        result = evaluate_join_values("id", {"id": "Int"}, {"id": "Int"}, [1, 2], [3, 4], True)
        assert result.verdict == ValidationVerdict.VALID
        assert result.present_both is True
        assert result.coercible is True
        assert result.complete is True


# ===========================================================================
# satisfy() mapping
# ===========================================================================


@pytest.mark.unit
class TestSatisfy:
    def test_satisfied_happy_path(self) -> None:
        result = satisfy_requirement(_req(geometry="Point"), _report())
        assert result.state == SatisfactionState.SATISFIED
        assert result.reasons == ()
        assert result.validation_verdict == ValidationVerdict.VALID
        assert len(result.validation_ref) == 64

    def test_invalid_maps(self) -> None:
        from lunar_gis.data.contracts import ValidationCheck

        report = _report(
            verdict=ValidationVerdict.INVALID,
            checks=(ValidationCheck("crs", False, False, "bad"),),
        )
        result = satisfy_requirement(_req(), report)
        assert result.state == SatisfactionState.NOT_SATISFIED
        assert result.reasons == ("invalid:crs",)

    def test_empty_never_satisfies(self) -> None:
        report = _report(verdict=ValidationVerdict.EMPTY)
        assert satisfy_requirement(_req(), report).state == SatisfactionState.NOT_SATISFIED
        # even with no attribute constraints
        assert satisfy_requirement(_req(required_fields=[]), report).reasons == ("empty-dataset",)

    def test_deferred_blocks(self) -> None:
        req = parse_requirement(
            {
                "name": "r",
                "extent": {"xmin": 0.0, "ymin": 0.0, "xmax": 1.0, "ymax": 1.0, "crs_authid": "EPSG:4326"},
            }
        )
        report = _report(extent=None, coverage_met=None)
        result = satisfy_requirement(req, report)
        assert result.state == SatisfactionState.UNKNOWN_DEFERRED
        assert result.reasons == ("deferred:extent",)

    def test_deferred_crs(self) -> None:
        req = parse_requirement({"name": "r", "crs": {"authid": "EPSG:4326"}})
        report = _report(crs_authid=None, crs_known=False)
        assert satisfy_requirement(req, report).state == SatisfactionState.UNKNOWN_DEFERRED

    def test_deferred_fields(self) -> None:
        req = parse_requirement({"name": "r", "required_fields": ["id"]})
        report = _report(field_list=(), fields_state=ValueState.UNKNOWN)
        assert satisfy_requirement(req, report).state == SatisfactionState.UNKNOWN_DEFERRED

    def test_deferred_temporal(self) -> None:
        req = parse_requirement({"name": "r", "temporal": {"has_time": True}})
        report = _report(has_time=None)
        assert satisfy_requirement(req, report).state == SatisfactionState.UNKNOWN_DEFERRED

    def test_partial_terminal(self) -> None:
        report = _report(validity="PARTIAL", validity_sample=(2, 10))
        result = satisfy_requirement(_req(geometry="Point"), report)
        assert result.state == SatisfactionState.PARTIAL
        assert result.reasons == ("partial-validity",)

    def test_constraint_mismatches(self) -> None:
        assert satisfy_requirement(_req(geometry="Polygon"), _report()).state == SatisfactionState.NOT_SATISFIED
        assert satisfy_requirement(_req(required_fields=["nope"]), _report()).reasons == ("schema-gap",)
        assert satisfy_requirement(
            parse_requirement({"name": "r", "crs": {"authid": "EPSG:3857"}}), _report()
        ).reasons == ("crs-mismatch",)
        assert satisfy_requirement(_req(temporal={"has_time": True}), _report(has_time=False)).reasons == (
            "temporal-mismatch",
        )

    def test_coverage_false(self) -> None:
        req = parse_requirement(
            {
                "name": "r",
                "extent": {"xmin": 0.0, "ymin": 0.0, "xmax": 1.0, "ymax": 1.0, "crs_authid": "EPSG:4326"},
            }
        )
        report = _report(coverage_met=False)
        assert satisfy_requirement(req, report).reasons == ("coverage-gap",)

    def test_evidence_templated(self) -> None:
        from lunar_gis.data.contracts import ValidationCheck

        report = _report(checks=(ValidationCheck("schema", True, False, "ok"),))
        result = satisfy_requirement(_req(), report)
        assert result.evidence == ("schema=pass:ok",)


# ===========================================================================
# evaluate_join_values
# ===========================================================================


@pytest.mark.unit
class TestJoinValues:
    def test_missing_key(self) -> None:
        result = evaluate_join_values("k", {"id": "Int"}, {"id": "Int"}, [1], [1], True)
        assert result.verdict == ValidationVerdict.INVALID
        assert result.present_both is False

    def test_incompatible_types(self) -> None:
        result = evaluate_join_values("id", {"id": "String"}, {"id": "Int"}, ["a"], [1], True)
        assert result.verdict == ValidationVerdict.INVALID
        assert result.coercible is False

    def test_int_double_widening(self) -> None:
        result = evaluate_join_values("id", {"id": "Int"}, {"id": "Double"}, [1], [1.0], True)
        assert result.verdict == ValidationVerdict.VALID

    def test_nulls_rejected(self) -> None:
        result = evaluate_join_values("id", {"id": "Int"}, {"id": "Int"}, [1, None], [2], True)
        assert result.verdict == ValidationVerdict.INVALID
        assert result.nulls_found is True

    def test_duplicates_rejected(self) -> None:
        result = evaluate_join_values("id", {"id": "Int"}, {"id": "Int"}, [1, 1], [2], True)
        assert result.verdict == ValidationVerdict.INVALID
        assert result.duplicates_found is True

    def test_cross_side_duplicates_rejected(self) -> None:
        result = evaluate_join_values("id", {"id": "Int"}, {"id": "Int"}, [1], [1], True)
        assert result.verdict == ValidationVerdict.INVALID
        assert result.duplicates_found is True

    def test_incomplete_flagged(self) -> None:
        result = evaluate_join_values("id", {"id": "Int"}, {"id": "Int"}, [1], [2], False)
        assert result.verdict == ValidationVerdict.VALID
        assert result.complete is False


# ===========================================================================
# Suffix + magic gates
# ===========================================================================


@pytest.mark.unit
class TestGates:
    def test_suffix_allowlist(self) -> None:
        ok, _ = check_suffix("/data/x.gpkg")
        assert ok is True
        ok, _ = check_suffix("/data/x.tif")
        assert ok is True
        ok, _ = check_suffix("/data/x.exe")
        assert ok is False
        ok, _ = check_suffix("/data/x.py")
        assert ok is False
        ok, _ = check_suffix("/data/x.unknown")
        assert ok is False

    def test_magic_gpkg(self, tmp_path) -> None:
        target = tmp_path / "x.gpkg"
        target.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
        ok, _ = check_magic(str(target))
        assert ok is True

    def test_magic_mismatch(self, tmp_path) -> None:
        target = tmp_path / "x.gpkg"
        target.write_bytes(b"#!/bin/sh\necho hi\n")
        ok, _ = check_magic(str(target))
        assert ok is False

    def test_magic_geojson(self, tmp_path) -> None:
        target = tmp_path / "x.geojson"
        target.write_bytes(b'{"type": "FeatureCollection"}')
        ok, _ = check_magic(str(target))
        assert ok is True

    def test_magic_empty(self, tmp_path) -> None:
        target = tmp_path / "x.geojson"
        target.write_bytes(b"")
        ok, _ = check_magic(str(target))
        assert ok is False

    def test_magic_missing_file(self, tmp_path) -> None:
        ok, detail = check_magic(str(tmp_path / "nope.gpkg"))
        assert ok is False
        assert "unreadable" in detail


# ===========================================================================
# validate_project_layer with fakes
# ===========================================================================


@pytest.mark.unit
class TestProjectLayerValidation:
    def test_valid_layer(self) -> None:
        layer = _layer()
        record = _record()
        report = validate_project_layer(record, layer)
        assert report.verdict == ValidationVerdict.VALID
        assert report.subject_kind == "layer-ref"
        assert report.geometry_canonical == "Point"
        assert report.validity == "FULL"
        assert report.validity_sample == (3, 3)
        assert [c.name for c in report.checks] == [
            "parseability",
            "emptiness",
            "schema",
            "crs",
            "geometry",
            "coverage",
        ]

    def test_invalid_layer(self) -> None:
        layer = _layer(is_valid=False)
        report = validate_project_layer(_record(), layer)
        assert report.verdict == ValidationVerdict.INVALID
        assert report.checks[0].name == "parseability"

    def test_empty_layer(self) -> None:
        layer = _layer(n_features=0)
        report = validate_project_layer(_record(), layer)
        assert report.verdict == ValidationVerdict.EMPTY
        skipped = [c for c in report.checks if c.skipped]
        assert {c.name for c in skipped} == {"schema", "crs", "geometry", "coverage"}
        assert all("skipped-empty" in c.detail for c in skipped)

    def test_invalid_geometry(self) -> None:
        layer = _layer(valid_geometry=False)
        report = validate_project_layer(_record(), layer)
        assert report.verdict == ValidationVerdict.INVALID
        assert report.checks[-1].name == "geometry"

    def test_partial_sampling_deterministic(self) -> None:
        many = FakeLayer(
            layer_id="m",
            name="m",
            provider="ogr",
            geometry_type=0,
            feature_count=5,
            crs_authid="EPSG:4326",
            extent=FakeExtent(0.0, 0.0, 1.0, 1.0),
            fields=FakeFields([FakeField("id", "Int")]),
            is_valid=True,
            features=[FakeFeature(fid=i, attributes={"id": i}) for i in (5, 3, 1, 2, 4)],
        )
        report = validate_project_layer(_record("m"), many)
        assert report.verdict == ValidationVerdict.VALID
        assert report.validity == "FULL"
        # out-of-order fids still deterministic: sorted head evaluated
        again = validate_project_layer(_record("m"), many)
        assert report.validity_sample == again.validity_sample

    def test_partial_when_capped(self) -> None:
        from lunar_gis.data import validation_qgis as module

        many = FakeLayer(
            layer_id="m",
            name="m",
            provider="ogr",
            geometry_type=0,
            feature_count=10,
            crs_authid="EPSG:4326",
            extent=FakeExtent(0.0, 0.0, 1.0, 1.0),
            fields=FakeFields([FakeField("id", "Int")]),
            is_valid=True,
            features=[FakeFeature(fid=i, attributes={"id": i}) for i in range(1, 11)],
        )
        original = module.VALIDITY_SCAN_CAP
        module.VALIDITY_SCAN_CAP = 3
        try:
            report = validate_project_layer(_record("m"), many)
        finally:
            module.VALIDITY_SCAN_CAP = original
        assert report.validity == "PARTIAL"
        assert report.validity_sample == (3, 10)

    def test_stale_snapshot_refuses(self) -> None:
        layer = _layer()
        record = _record()
        project = FakeProject(layers={"a": layer}, dirty=True)
        inventory = discover_project(project, taken_at=TAKEN_AT)
        report = validate_project_layer(record, layer, project=project, snapshot=inventory)
        assert report.verdict == ValidationVerdict.INVALID
        assert report.checks[0].name == "snapshot-freshness"
        assert "stale-snapshot" in report.warnings

    def test_fresh_snapshot_passes(self) -> None:
        layer = _layer()
        project = FakeProject(layers={"a": layer}, dirty=False)
        inventory = discover_project(project, taken_at=TAKEN_AT)
        record = inventory.records[0]
        report = validate_project_layer(record, layer, project=project, snapshot=inventory)
        assert report.verdict == ValidationVerdict.VALID

    def test_no_snapshot_warns_not_fails(self) -> None:
        layer = _layer()
        report = validate_project_layer(_record(), layer, project=FakeProject(layers={"a": layer}))
        assert report.verdict == ValidationVerdict.VALID


@pytest.mark.unit
class TestRequirementCoverage:
    def test_coverage_met_same_crs_without_qgis(self) -> None:
        # No QGIS runtime here: transform unavailable → deferred, never guessed.
        req = parse_requirement(
            {
                "name": "r",
                "extent": {"xmin": 0.0, "ymin": 0.0, "xmax": 1.0, "ymax": 1.0, "crs_authid": "EPSG:4326"},
            }
        )
        report = validate_project_layer(_record(), _layer(), requirement=req)
        assert report.coverage_met is None
        assert report.coverage_method == "qgis-unavailable"

    def test_unknown_extent_deferred(self) -> None:
        layer = _layer()
        layer._has_extent = False
        req = parse_requirement(
            {
                "name": "r",
                "extent": {"xmin": 0.0, "ymin": 0.0, "xmax": 1.0, "ymax": 1.0, "crs_authid": "EPSG:4326"},
            }
        )
        report = validate_project_layer(_record(), layer, requirement=req)
        assert report.coverage_met is None


# ===========================================================================
# validate_local_file with fakes (suffix/magic/resolution only — QGIS open
# needs the runtime; covered live + qgis-marked tests)
# ===========================================================================


@pytest.mark.unit
class TestLocalFileGates:
    def test_rejects_script_suffix(self, tmp_path) -> None:
        target = tmp_path / "evil.py"
        target.write_bytes(b"print(1)\n")
        report = validate_local_file(str(target))
        assert report.verdict == ValidationVerdict.INVALID
        assert report.subject_kind == "file"

    def test_rejects_unknown_suffix(self, tmp_path) -> None:
        target = tmp_path / "x.xyz"
        target.write_bytes(b"data")
        report = validate_local_file(str(target))
        assert report.verdict == ValidationVerdict.INVALID

    def test_rejects_directory(self, tmp_path) -> None:
        report = validate_local_file(str(tmp_path))
        assert report.verdict == ValidationVerdict.INVALID

    def test_rejects_missing(self, tmp_path) -> None:
        report = validate_local_file(str(tmp_path / "gone.gpkg"))
        assert report.verdict == ValidationVerdict.INVALID

    def test_sandbox_escape_rejected(self, tmp_path) -> None:
        outside = tmp_path / "outside.gpkg"
        outside.write_bytes(b"SQLite format 3\x00")
        sandbox = tmp_path / "box"
        sandbox.mkdir()
        report = validate_local_file("../outside.gpkg", sandbox_root=str(sandbox))
        assert report.verdict == ValidationVerdict.INVALID

    def test_sandbox_member_accepted_for_gating(self, tmp_path) -> None:
        sandbox = tmp_path / "box"
        sandbox.mkdir()
        member = sandbox / "in.gpkg"
        member.write_bytes(b"SQLite format 3\x00" + b"\x00" * 64)
        # QGIS absent here → parseability fails closed, but allowlist passes.
        report = validate_local_file("in.gpkg", sandbox_root=str(sandbox))
        assert report.verdict == ValidationVerdict.INVALID
        assert report.checks[0].name == "parseability"
        assert "qgis-runtime-unavailable" in report.checks[0].detail

    def test_subject_minimized(self, tmp_path) -> None:
        report = validate_local_file(str(tmp_path / "gone.gpkg"))
        assert report.subject_kind == "file"
        assert report.subject_ref.endswith("gone.gpkg")


# ===========================================================================
# validate_join_key with fakes
# ===========================================================================


@pytest.mark.unit
class TestJoinKey:
    def _layers(self):
        left = FakeLayer(
            layer_id="l",
            fields=FakeFields([FakeField("id", "Int")]),
            features=[FakeFeature(fid=1, attributes={"id": 1}), FakeFeature(fid=2, attributes={"id": 2})],
            feature_count=2,
        )
        right = FakeLayer(
            layer_id="r",
            fields=FakeFields([FakeField("id", "Int")]),
            features=[FakeFeature(fid=1, attributes={"id": 3}), FakeFeature(fid=2, attributes={"id": 4})],
            feature_count=2,
        )
        return left, right

    def test_valid_key(self) -> None:
        left, right = self._layers()
        result = validate_join_key(left, right, "id")
        assert result.verdict == ValidationVerdict.VALID
        assert result.complete is True
        assert result.rows_scanned == 4

    def test_missing_key(self) -> None:
        left, right = self._layers()
        result = validate_join_key(left, right, "nope")
        assert result.verdict == ValidationVerdict.INVALID
        assert result.present_both is False

    def test_duplicates_invalid(self) -> None:
        left, right = self._layers()
        left._features = [FakeFeature(fid=1, attributes={"id": 1}), FakeFeature(fid=2, attributes={"id": 1})]
        result = validate_join_key(left, right, "id")
        assert result.verdict == ValidationVerdict.INVALID
        assert result.duplicates_found is True

    def test_nulls_invalid(self) -> None:
        left, right = self._layers()
        left._features = [FakeFeature(fid=1, attributes={"id": None})]
        result = validate_join_key(left, right, "id")
        assert result.verdict == ValidationVerdict.INVALID
        assert result.nulls_found is True

    def test_capped_sample_marks_incomplete(self) -> None:
        from lunar_gis.data import validation_qgis as module

        left, right = self._layers()
        left._features = [FakeFeature(fid=i, attributes={"id": i}) for i in range(10)]
        left._feature_count = 10
        original = module.JOIN_SCAN_CAP
        module.JOIN_SCAN_CAP = 3
        try:
            result = validate_join_key(left, right, "id")
        finally:
            module.JOIN_SCAN_CAP = original
        assert result.complete is False


# ===========================================================================
# Security: no URL/network/unsafe mechanisms; redaction preserved
# ===========================================================================


@pytest.mark.unit
class TestValidationSecurity:
    def test_no_network_or_exec_imports(self) -> None:
        import pathlib

        source = pathlib.Path(validation_module.__file__).read_text(encoding="utf-8")
        for token in (
            "import urllib",
            "import requests",
            "import socket",
            "import subprocess",
            "import pickle",
            "import yaml",
            "import tarfile",
            "eval(",
            "exec(",
            "os.system",
        ):
            assert token not in source, token

    def test_no_top_level_qgis_import(self) -> None:
        import ast
        import pathlib

        tree = ast.parse(pathlib.Path(validation_module.__file__).read_text(encoding="utf-8"))
        top_imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        for node in top_imports:
            if isinstance(node, ast.Import):
                assert not any(a.name.split(".")[0] == "qgis" for a in node.names)
            else:
                module = node.module or ""
                assert module.split(".")[0] != "qgis"
                # only QGIS-free contracts may be imported at top level
                assert module in ("__future__", "math", "os", "datetime", "typing", "lunar_gis.data.contracts")

    def test_probe_does_not_mutate_project(self) -> None:
        layer = _layer()
        project = FakeProject(layers={"a": layer})
        before = list(project.mapLayers().keys())
        validate_project_layer(_record(), layer, project=project)
        validate_join_key(layer, layer, "id")
        assert list(project.mapLayers().keys()) == before

    def test_redacted_subject_only(self) -> None:
        layer = _layer()
        layer._source = "postgresql://boss:hunter2@db:5432/gis"
        record = discover_project(FakeProject(layers={"a": layer}), taken_at=TAKEN_AT).records[0]
        report = validate_project_layer(record, layer)
        assert "hunter2" not in report_canonical_json(report)


# ===========================================================================
# Import boundary
# ===========================================================================


@pytest.mark.unit
class TestValidationImportBoundary:
    def test_validation_importable_with_qgis_blocked(self) -> None:
        import importlib
        import sys

        blocked = sys.modules.get("qgis")
        sys.modules["qgis"] = None  # type: ignore[assignment]
        try:
            for module in [m for m in list(sys.modules) if m.startswith("lunar_gis.data.validation")]:
                del sys.modules[module]
            reloaded = importlib.import_module("lunar_gis.data.validation_qgis")
            assert reloaded.SUFFIX_ALLOWLIST is not None
        finally:
            if blocked is not None:
                sys.modules["qgis"] = blocked
            else:
                sys.modules.pop("qgis", None)

    def test_qgis_absent_degrades_not_exceptions(self, tmp_path) -> None:
        import sys

        assert "qgis" not in sys.modules or sys.modules.get("qgis") is None
        # Duck-typed layer validation proceeds (QGIS steps defer inside).
        report = validate_project_layer(_record(), _layer())
        assert report.verdict == ValidationVerdict.VALID
        assert "qgis-runtime-absent:qgis-powered-steps-deferred" in report.warnings
        # File probe construction genuinely needs the runtime → fail closed.
        target = tmp_path / "x.gpkg"
        target.write_bytes(b"SQLite format 3\x00" + b"\x00" * 64)
        file_report = validate_local_file(str(target))
        assert file_report.verdict == ValidationVerdict.INVALID

    def test_no_reverse_import(self) -> None:
        import pathlib

        source = pathlib.Path(validation_module.__file__).read_text(encoding="utf-8")
        assert "from lunar_gis.project" not in source
        assert "from lunar_gis.agent" not in source
        assert "from lunar_gis.ai" not in source


try:
    from qgis.core import QgsProject  # noqa: F401 — QGIS availability detection only

    HAS_QGIS = True
except ImportError:
    HAS_QGIS = False


@pytest.mark.qgis
@pytest.mark.skipif(not HAS_QGIS, reason="QGIS runtime not available")
class TestValidationQgisRuntime:
    def test_memory_layer_valid_and_satisfied(self) -> None:
        from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer

        from lunar_gis.data.contracts import parse_requirement as parse
        from lunar_gis.data.contracts import satisfy_requirement as satisfy

        project = QgsProject.instance()
        layer = QgsVectorLayer("Point?crs=EPSG:4326&field=id:integer", "vruntime", "memory")
        assert layer.isValid()
        layer.startEditing()
        feature = QgsFeature(layer.fields())
        feature.setAttributes([7])
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(1.0, 2.0)))
        assert layer.addFeature(feature)
        assert layer.commitChanges()
        project.addMapLayer(layer)
        try:
            count_before = len(project.mapLayers())
            from lunar_gis.data.discovery_qgis import discover_project as discover

            inventory = discover(project, taken_at=TAKEN_AT)
            assert len(project.mapLayers()) == count_before
            rec = next(r for r in inventory.records if r.layer_id == layer.id())
            req = parse({"name": "r", "geometry": "Point", "required_fields": ["id"], "crs": {"authid": "EPSG:4326"}})
            report = validate_project_layer(rec, layer, requirement=req)
            assert report.verdict == ValidationVerdict.VALID
            assert report.validity == "FULL"
            assert report.coverage_met is True
            outcome = satisfy(req, report)
            assert outcome.state == SatisfactionState.SATISFIED
        finally:
            project.removeMapLayer(layer.id())

    def test_empty_memory_layer_empty(self) -> None:
        from qgis.core import QgsVectorLayer

        project = QgsProject.instance()
        layer = QgsVectorLayer("Point?crs=EPSG:4326&field=id:integer", "vempty", "memory")
        assert layer.isValid()
        project.addMapLayer(layer)
        try:
            from lunar_gis.data.discovery_qgis import discover_project as discover

            inventory = discover(project, taken_at=TAKEN_AT)
            rec = next(r for r in inventory.records if r.layer_id == layer.id())
            report = validate_project_layer(rec, layer)
            assert report.verdict == ValidationVerdict.EMPTY
        finally:
            project.removeMapLayer(layer.id())

    def test_join_key_live(self) -> None:
        from qgis.core import QgsFeature, QgsVectorLayer

        project = QgsProject.instance()
        left = QgsVectorLayer("None?field=id:integer", "jleft", "memory")
        right = QgsVectorLayer("None?field=id:integer", "jright", "memory")
        for layer, values in ((left, [1, 2]), (right, [3, 4])):
            assert layer.isValid()
            layer.startEditing()
            for value in values:
                feature = QgsFeature(layer.fields())
                feature.setAttributes([value])
                assert layer.addFeature(feature)
            assert layer.commitChanges()
            project.addMapLayer(layer)
        try:
            result = validate_join_key(left, right, "id")
            assert result.verdict == ValidationVerdict.VALID
            assert result.complete is True
        finally:
            project.removeMapLayer(left.id())
            project.removeMapLayer(right.id())

    def test_local_gpkg_file_live(self, tmp_path) -> None:
        from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorFileWriter, QgsVectorLayer

        project = QgsProject.instance()
        count_before = len(project.mapLayers())
        layer = QgsVectorLayer("Point?crs=EPSG:4326&field=id:integer", "fexport", "memory")
        assert layer.isValid()
        layer.startEditing()
        feature = QgsFeature(layer.fields())
        feature.setAttributes([1])
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(1.0, 1.0)))
        assert layer.addFeature(feature)
        assert layer.commitChanges()
        target = str(tmp_path / "probe.gpkg")
        error, _, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer, target, project.transformContext(), QgsVectorFileWriter.SaveVectorOptions()
        )
        assert error == QgsVectorFileWriter.NoError
        report = validate_local_file(target)
        assert report.verdict == ValidationVerdict.VALID
        assert report.subject_kind == "file"
        assert len(project.mapLayers()) == count_before
