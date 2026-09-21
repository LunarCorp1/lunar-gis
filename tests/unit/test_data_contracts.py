"""Unit tests for M4-T02 data contracts: requirement parsing, geometry
canonicalization, redaction, snapshot identity, and deterministic
classification. All QGIS-free."""

from __future__ import annotations

import json

import pytest

from lunar_gis.data import contracts as contracts_module
from lunar_gis.data.contracts import (
    AvailabilityState,
    DataContractError,
    LayerExtent,
    LayerField,
    LayerInventory,
    LayerRecord,
    MissingReason,
    Reachability,
    StorageKind,
    ValueState,
    canonicalize_geometry,
    classification_canonical_json,
    classify_requirement,
    compute_snapshot_id,
    geometry_satisfies,
    minimize_path,
    parse_requirement,
    redact_source,
    requirement_canonical_json,
    requirement_to_dict,
    snapshot_pin,
)


def _record(layer_id: str = "a", **overrides) -> LayerRecord:
    fields = {
        "layer_id": layer_id,
        "name": layer_id,
        "provider": "ogr",
        "geometry_type": "Point",
        "crs_authid": "EPSG:4326",
        "crs_known": True,
        "feature_count": 10,
        "feature_count_state": ValueState.KNOWN,
        "extent": LayerExtent(0.0, 0.0, 10.0, 10.0, "EPSG:4326"),
        "extent_state": ValueState.KNOWN,
        "fields": (LayerField("id", "Int"), LayerField("name", "String")),
        "fields_state": ValueState.KNOWN,
        "source_redacted": "",
        "storage": StorageKind.FILE,
        "reachable": Reachability.UNKNOWN,
        "has_time": False,
        "valid": True,
    }
    fields.update(overrides)
    return LayerRecord(**fields)  # type: ignore[arg-type]


def _inventory(*records: LayerRecord, truncated: bool = False) -> LayerInventory:
    ids = sorted(r.layer_id for r in records)
    taken_at = "2026-01-01T00:00:00+00:00"
    return LayerInventory(
        records=tuple(records),
        snapshot_id=compute_snapshot_id(ids, taken_at),
        taken_at=taken_at,
        project_dirty=False,
        total_count=len(records),
        truncated=truncated,
    )


# ===========================================================================
# Requirement parsing — valid
# ===========================================================================


@pytest.mark.unit
class TestParseValid:
    def test_minimal_name_only(self) -> None:
        req = parse_requirement({"name": "roads"})
        assert req.name == "roads"
        assert req.geometry == "Any"
        assert req.required_fields == ()
        assert req.crs_authid is None
        assert req.extent is None
        assert req.coverage_threshold == 1.0
        assert req.acceptable_sources == ("local-project", "local-file")
        assert req.requirement_version == "1.0"

    def test_full_requirement(self) -> None:
        req = parse_requirement(
            {
                "name": "parcels",
                "geometry": "Polygon",
                "required_fields": ["id", "area"],
                "field_types": {"area": "Double"},
                "crs": {"authid": "EPSG:3857"},
                "extent": {"xmin": 0.0, "ymin": 0.0, "xmax": 5.0, "ymax": 5.0, "crs_authid": "EPSG:3857"},
                "coverage_threshold": 0.9,
                "temporal": {"has_time": False},
                "acceptable_sources": ["local-project"],
                "transformations_allowed": ["reproject-vector", "clip"],
            }
        )
        assert req.geometry == "Polygon"
        assert req.field_types == (("area", "Double"),)
        assert req.extent is not None and req.extent.xmax == 5.0
        assert req.coverage_threshold == 0.9
        assert req.transformations_allowed == ("reproject-vector", "clip")

    def test_provider_source_pattern(self) -> None:
        req = parse_requirement({"name": "x", "acceptable_sources": ["provider:stac.earth-search"]})
        assert req.acceptable_sources == ("provider:stac.earth-search",)

    def test_empty_transformations_allowed_means_no_transforms(self) -> None:
        req = parse_requirement({"name": "x", "transformations_allowed": []})
        assert req.transformations_allowed == ()


# ===========================================================================
# Requirement parsing — malformed
# ===========================================================================


@pytest.mark.unit
class TestParseMalformed:
    def test_not_a_dict(self) -> None:
        with pytest.raises(DataContractError):
            parse_requirement(["name"])  # type: ignore[arg-type]

    def test_missing_name(self) -> None:
        with pytest.raises(DataContractError):
            parse_requirement({"geometry": "Point"})

    def test_empty_name(self) -> None:
        with pytest.raises(DataContractError):
            parse_requirement({"name": "  "})

    def test_unknown_field_rejected(self) -> None:
        # additionalProperties:false equivalent — also the LLM-label hook:
        # proposer-supplied labels/classifications cannot sneak in.
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "label": "AVAILABLE"})
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "classification": "available"})

    def test_verification_present_rejected(self) -> None:
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "verification": "VERIFIED"})

    def test_null_geometry_rejected_no_unions(self) -> None:
        # null|X unions are forbidden: absent = unconstrained.
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "geometry": None})

    def test_closed_geometry_enum(self) -> None:
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "geometry": "MultiPoint"})
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "geometry": "point"})

    def test_invalid_extent_shapes(self) -> None:
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "extent": {"xmin": 0.0}})
        with pytest.raises(DataContractError):
            parse_requirement(
                {"name": "x", "extent": {"xmin": 5.0, "ymin": 0.0, "xmax": 1.0, "ymax": 1.0, "crs_authid": "EPSG:4326"}}
            )
        with pytest.raises(DataContractError):
            parse_requirement(
                {"name": "x", "extent": {"xmin": 0.0, "ymin": 0.0, "xmax": 1.0, "ymax": 1.0, "crs_authid": ""}}
            )
        with pytest.raises(DataContractError):
            parse_requirement(
                {"name": "x", "extent": {"xmin": "0", "ymin": 0.0, "xmax": 1.0, "ymax": 1.0, "crs_authid": "EPSG:4326"}}
            )

    def test_coverage_threshold_range(self) -> None:
        for bad in (0.0, -0.5, 1.5, "1.0", True, None):
            with pytest.raises(DataContractError):
                parse_requirement({"name": "x", "coverage_threshold": bad})

    def test_invalid_provider_identifier(self) -> None:
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "acceptable_sources": ["provider:"]})
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "acceptable_sources": ["https://example.com/x"]})
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "acceptable_sources": []})

    def test_invalid_direction(self) -> None:
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "transformations_allowed": ["raster-vector"]})
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "transformations_allowed": ["buffer"]})

    def test_qvariant_subset_boundaries(self) -> None:
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "field_types": {"a": "Variant"}})
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "field_types": {"a": "int"}})
        # every closed member accepted
        req = parse_requirement(
            {
                "name": "x",
                "field_types": {
                    "a": "String",
                    "b": "Int",
                    "c": "Double",
                    "d": "Date",
                    "e": "DateTime",
                    "f": "Bool",
                    "g": "StringList",
                },
            }
        )
        assert len(req.field_types) == 7

    def test_temporal_shape(self) -> None:
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "temporal": {"has_time": "yes"}})
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "temporal": {}})

    def test_crs_shape(self) -> None:
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "crs": {"authid": "EPSG:4326", "extra": 1}})
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "crs": {"authid": ""}})

    def test_required_fields_shape(self) -> None:
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "required_fields": ["ok", ""]})
        with pytest.raises(DataContractError):
            parse_requirement({"name": "x", "required_fields": "id"})


# ===========================================================================
# Serialization determinism
# ===========================================================================


@pytest.mark.unit
class TestSerialization:
    def test_canonical_json_stable_and_sorted(self) -> None:
        req = parse_requirement({"name": "b", "geometry": "Point", "crs": {"authid": "EPSG:4326"}})
        first = requirement_canonical_json(req)
        second = requirement_canonical_json(parse_requirement(json.loads(first)))
        assert first == second
        payload = json.loads(first)
        assert list(payload.keys()) == sorted(payload.keys())

    def test_absence_pattern_roundtrip(self) -> None:
        req = parse_requirement({"name": "x"})
        payload = requirement_to_dict(req)
        assert "crs" not in payload
        assert "extent" not in payload
        assert "temporal" not in payload
        assert "field_types" not in payload
        assert payload["acceptable_sources"] == ["local-project", "local-file"]

    def test_dataclasses_frozen(self) -> None:
        req = parse_requirement({"name": "x"})
        with pytest.raises(Exception):
            req.name = "y"  # type: ignore[misc]
        rec = _record()
        with pytest.raises(Exception):
            rec.name = "y"  # type: ignore[misc]


# ===========================================================================
# Geometry canonicalization
# ===========================================================================


@pytest.mark.unit
class TestCanonicalize:
    def test_none_and_unknown_strings(self) -> None:
        assert canonicalize_geometry(None) == "Unknown"
        for text in ("", "unknown", "Null", "NoGeometry"):
            assert canonicalize_geometry(text) == "Unknown"

    def test_point_family(self) -> None:
        assert canonicalize_geometry("Point") == "Point"
        assert canonicalize_geometry("Qgis.GeometryType.Point") == "Point"
        assert canonicalize_geometry("MultiPoint") == "Point"
        # QGIS 3/4 geometryType() numbering (verified QGIS 4.2.0): 0=Point
        assert canonicalize_geometry("0") == "Point"
        assert canonicalize_geometry(0) == "Point"

    def test_line_polygon_families(self) -> None:
        assert canonicalize_geometry("LineString") == "LineString"
        assert canonicalize_geometry("Line") == "LineString"
        assert canonicalize_geometry("MultiLineString") == "LineString"
        assert canonicalize_geometry("1") == "LineString"
        assert canonicalize_geometry("Polygon") == "Polygon"
        assert canonicalize_geometry("Qgis.GeometryType.Polygon") == "Polygon"
        assert canonicalize_geometry("2") == "Polygon"
        assert canonicalize_geometry("3") == "Unknown"
        assert canonicalize_geometry("4") == "Unknown"

    def test_raster_table_markers(self) -> None:
        assert canonicalize_geometry("Raster") == "Raster"
        assert canonicalize_geometry("Table") == "Table"

    def test_unrecognized_is_unknown(self) -> None:
        assert canonicalize_geometry("Mesh") == "Unknown"
        assert canonicalize_geometry("whatever") == "Unknown"

    def test_satisfies(self) -> None:
        assert geometry_satisfies("Any", "Unknown") is True
        assert geometry_satisfies("Point", "Point") is True
        assert geometry_satisfies("Point", "Unknown") is False
        assert geometry_satisfies("Point", "Polygon") is False


@pytest.mark.unit
class TestFieldNormalization:
    def test_provider_names_normalize(self) -> None:
        from lunar_gis.data.contracts import normalize_field_type

        assert normalize_field_type("integer") == "Int"
        assert normalize_field_type("string") == "String"
        assert normalize_field_type("double") == "Double"
        assert normalize_field_type("Int") == "Int"
        assert normalize_field_type("UNKNOWN_TYPE") == "UNKNOWN_TYPE"

    def test_real_provider_types_satisfy(self) -> None:
        # lowercase OGR/memory type names meet closed-subset requirements.
        req = parse_requirement({"name": "x", "required_fields": ["id"], "field_types": {"id": "Int"}})
        rec = _record(fields=(LayerField("id", "integer"),))
        result = classify_requirement(req, _inventory(rec))
        assert result.state == AvailabilityState.AVAILABLE

    def test_unmapped_type_is_schema_gap(self) -> None:
        req = parse_requirement({"name": "x", "required_fields": ["g"], "field_types": {"g": "String"}})
        rec = _record(fields=(LayerField("g", "jsonb"),))
        result = classify_requirement(req, _inventory(rec))
        assert result.state == AvailabilityState.MISSING
        assert result.missing_reason == MissingReason.SCHEMA_GAP


# ===========================================================================
# Redaction / minimization
# ===========================================================================


@pytest.mark.unit
class TestRedaction:
    def test_credentials_stripped(self) -> None:
        out = redact_source("postgresql://user:secret@host:5432/db")
        assert out == "postgresql://host:5432/db"

    def test_no_credentials_unchanged(self) -> None:
        assert redact_source("/data/roads.gpkg") == "/data/roads.gpkg"

    def test_home_collapsed(self) -> None:
        import os

        home = os.path.expanduser("~")
        assert home and home != "~"
        out = redact_source(home + "/data/x.gpkg")
        assert out == "~/data/x.gpkg"

    def test_non_string_safe(self) -> None:
        assert redact_source(None) == ""  # type: ignore[arg-type]
        assert minimize_path("") == ""
        assert minimize_path(None) == ""  # type: ignore[arg-type]


# ===========================================================================
# Snapshot identity
# ===========================================================================


@pytest.mark.unit
class TestSnapshotIdentity:
    def test_id_deterministic(self) -> None:
        first = compute_snapshot_id(["a", "b"], "2026-01-01T00:00:00+00:00")
        second = compute_snapshot_id(["a", "b"], "2026-01-01T00:00:00+00:00")
        assert first == second and len(first) == 64

    def test_id_order_sensitive(self) -> None:
        taken = "2026-01-01T00:00:00+00:00"
        assert compute_snapshot_id(["a", "b"], taken) != compute_snapshot_id(["b", "a"], taken)

    def test_pin(self) -> None:
        inv = _inventory(_record("a"), _record("b"))
        pin = snapshot_pin(inv)
        assert pin.snapshot_id == inv.snapshot_id
        assert pin.record_count == 2
        assert pin.truncated is False


# ===========================================================================
# Classification — AVAILABLE
# ===========================================================================


@pytest.mark.unit
class TestClassifyAvailable:
    def test_happy_path(self) -> None:
        req = parse_requirement({"name": "pts", "geometry": "Point"})
        result = classify_requirement(req, _inventory(_record("a")))
        assert result.state == AvailabilityState.AVAILABLE
        assert result.layer_id == "a"
        assert result.missing_reason is None
        assert result.chain == ()
        assert result.provisional is True
        assert [e.check for e in result.evidence] == [
            "geometry",
            "fields",
            "crs",
            "reachability",
            "coverage",
            "validity",
            "temporal",
        ]
        assert all(e.passed for e in result.evidence)

    def test_any_geometry_matches_unknown(self) -> None:
        req = parse_requirement({"name": "x"})
        result = classify_requirement(req, _inventory(_record("a", geometry_type=None)))
        assert result.state == AvailabilityState.AVAILABLE

    def test_first_layer_in_order_wins(self) -> None:
        req = parse_requirement({"name": "x", "geometry": "Point"})
        result = classify_requirement(req, _inventory(_record("b"), _record("a")))
        assert result.layer_id == "a"

    def test_fields_and_types(self) -> None:
        req = parse_requirement({"name": "x", "required_fields": ["id", "area"], "field_types": {"area": "Double"}})
        good = _record("a", fields=(LayerField("id", "Int"), LayerField("area", "Double")))
        assert classify_requirement(req, _inventory(good)).state == AvailabilityState.AVAILABLE
        # Int widens to Double per frozen allowlist
        wide = _record("a", fields=(LayerField("id", "Int"), LayerField("area", "Int")))
        assert classify_requirement(req, _inventory(wide)).state == AvailabilityState.AVAILABLE
        # String does not coerce to Double
        bad = _record("a", fields=(LayerField("id", "Int"), LayerField("area", "String")))
        result = classify_requirement(req, _inventory(bad))
        assert result.state == AvailabilityState.MISSING
        assert result.missing_reason == MissingReason.SCHEMA_GAP

    def test_crs_match_and_absence(self) -> None:
        req = parse_requirement({"name": "x", "crs": {"authid": "EPSG:4326"}})
        assert classify_requirement(req, _inventory(_record())).state == AvailabilityState.AVAILABLE
        req2 = parse_requirement({"name": "x", "crs": {"authid": "EPSG:3857"}})
        result = classify_requirement(req2, _inventory(_record()))
        # CRS mismatch with everything else matching → DERIVABLE reproject, not AVAILABLE
        assert result.state == AvailabilityState.DERIVABLE
        assert result.chain[0].op == "reproject-vector"

    def test_coverage_estimate_same_crs(self) -> None:
        req = parse_requirement(
            {
                "name": "x",
                "extent": {"xmin": 1.0, "ymin": 1.0, "xmax": 2.0, "ymax": 2.0, "crs_authid": "EPSG:4326"},
            }
        )
        assert classify_requirement(req, _inventory(_record())).state == AvailabilityState.AVAILABLE

    def test_no_timestamps_in_verdict(self) -> None:
        req = parse_requirement({"name": "x"})
        result = classify_requirement(req, _inventory(_record()))
        payload = json.loads(classification_canonical_json(result))
        assert "taken_at" not in payload

    def test_repeat_call_identical(self) -> None:
        req = parse_requirement({"name": "x", "geometry": "Point"})
        inv = _inventory(_record("a"))
        assert classification_canonical_json(classify_requirement(req, inv)) == classification_canonical_json(
            classify_requirement(req, inv)
        )


# ===========================================================================
# Classification — UNKNOWN never AVAILABLE
# ===========================================================================


@pytest.mark.unit
class TestUnknownNeverAvailable:
    def test_unknown_geometry_typed(self) -> None:
        req = parse_requirement({"name": "x", "geometry": "Point"})
        result = classify_requirement(req, _inventory(_record(geometry_type=None)))
        assert result.state == AvailabilityState.MISSING
        assert result.missing_reason == MissingReason.NO_LAYER

    def test_unknown_fields_with_constraint(self) -> None:
        req = parse_requirement({"name": "x", "required_fields": ["id"]})
        rec = _record(fields=None, fields_state=ValueState.UNKNOWN)
        result = classify_requirement(req, _inventory(rec))
        assert result.state == AvailabilityState.MISSING
        assert result.missing_reason == MissingReason.UNKNOWN_DEFERRED

    def test_unknown_crs_with_constraint(self) -> None:
        req = parse_requirement({"name": "x", "crs": {"authid": "EPSG:4326"}})
        rec = _record(crs_authid=None, crs_known=False)
        result = classify_requirement(req, _inventory(rec))
        assert result.state == AvailabilityState.MISSING
        assert result.missing_reason == MissingReason.UNKNOWN_DEFERRED

    def test_unknown_extent_with_constraint(self) -> None:
        req = parse_requirement(
            {
                "name": "x",
                "extent": {"xmin": 0.0, "ymin": 0.0, "xmax": 1.0, "ymax": 1.0, "crs_authid": "EPSG:4326"},
            }
        )
        rec = _record(extent=None, extent_state=ValueState.UNKNOWN)
        result = classify_requirement(req, _inventory(rec))
        assert result.state == AvailabilityState.MISSING
        assert result.missing_reason == MissingReason.UNKNOWN_DEFERRED

    def test_cross_crs_extent_never_passes(self) -> None:
        req = parse_requirement(
            {
                "name": "x",
                "extent": {"xmin": 0.0, "ymin": 0.0, "xmax": 1.0, "ymax": 1.0, "crs_authid": "EPSG:3857"},
            }
        )
        result = classify_requirement(req, _inventory(_record()))
        assert result.state == AvailabilityState.MISSING
        assert result.missing_reason == MissingReason.UNKNOWN_DEFERRED

    def test_partial_coverage_never_available(self) -> None:
        req = parse_requirement(
            {
                "name": "x",
                "extent": {"xmin": 0.0, "ymin": 0.0, "xmax": 20.0, "ymax": 20.0, "crs_authid": "EPSG:4326"},
            }
        )
        result = classify_requirement(req, _inventory(_record()))
        assert result.state == AvailabilityState.MISSING
        assert result.missing_reason == MissingReason.COVERAGE_GAP

    def test_invalid_and_empty_layers(self) -> None:
        req = parse_requirement({"name": "x"})
        bad = _record(valid=False)
        result = classify_requirement(req, _inventory(bad))
        assert result.state == AvailabilityState.MISSING
        assert result.missing_reason == MissingReason.INVALID_CANDIDATE
        empty = _record(feature_count=0, feature_count_state=ValueState.KNOWN)
        result2 = classify_requirement(req, _inventory(empty))
        assert result2.state == AvailabilityState.MISSING
        assert result2.missing_reason == MissingReason.INVALID_CANDIDATE

    def test_unreachable_remote(self) -> None:
        req = parse_requirement({"name": "x"})
        rec = _record(provider="wfs", storage=StorageKind.REMOTE_SERVICE, reachable=Reachability.KNOWN_UNREACHABLE)
        result = classify_requirement(req, _inventory(rec))
        assert result.state == AvailabilityState.MISSING
        assert result.missing_reason == MissingReason.INVALID_CANDIDATE


# ===========================================================================
# Classification — DERIVABLE chains
# ===========================================================================


@pytest.mark.unit
class TestDerivable:
    def test_reproject_vector_chain(self) -> None:
        req = parse_requirement({"name": "x", "geometry": "Point", "crs": {"authid": "EPSG:3857"}})
        result = classify_requirement(req, _inventory(_record()))
        assert result.state == AvailabilityState.DERIVABLE
        assert len(result.chain) == 1
        step = result.chain[0]
        assert step.op == "reproject-vector"
        assert step.executor == "qgis-processing"
        assert step.step_schema_version == "1.0"
        assert step.executor_alg_ref is None
        assert step.provisional is True
        assert result.provisional is True
        assert dict(step.params)["target_crs"] == "EPSG:3857"

    def test_chain_tiebreak_layer_id_order(self) -> None:
        req = parse_requirement({"name": "x", "crs": {"authid": "EPSG:3857"}})
        result = classify_requirement(req, _inventory(_record("b"), _record("a")))
        assert result.state == AvailabilityState.DERIVABLE
        assert result.chain[0].input_refs == ("a",)

    def test_join_provisional_deterministic_key(self) -> None:
        req = parse_requirement({"name": "x", "required_fields": ["zip", "area"]})
        left = _record("a", fields=(LayerField("id", "Int"), LayerField("zip", "String")))
        right = _record("b", fields=(LayerField("id", "Int"), LayerField("area", "Double")))
        result = classify_requirement(req, _inventory(left, right))
        assert result.state == AvailabilityState.DERIVABLE
        step = result.chain[0]
        assert step.op == "join"
        assert dict(step.params)["key"] == "id"
        # cardinality is proposed, never asserted: validation confirms.
        assert dict(step.params)["cardinality"] == "1:1-proposed"
        assert step.provisional is True

    def test_join_key_choice_sorted_first(self) -> None:
        req = parse_requirement({"name": "x", "required_fields": ["a1", "b1"]})
        left = _record("a", fields=(LayerField("zkey", "Int"), LayerField("akey", "Int"), LayerField("a1", "String")))
        right = _record("b", fields=(LayerField("zkey", "Int"), LayerField("akey", "Int"), LayerField("b1", "String")))
        result = classify_requirement(req, _inventory(left, right))
        assert result.state == AvailabilityState.DERIVABLE
        assert dict(result.chain[0].params)["key"] == "akey"

    def test_conversion_provisional(self) -> None:
        req = parse_requirement({"name": "x", "geometry": "Point"})
        rec = _record(geometry_type="Raster", fields=(), provider="gdal")
        result = classify_requirement(req, _inventory(rec))
        assert result.state == AvailabilityState.DERIVABLE
        assert result.chain[0].op == "raster-to-vector"

    def test_clip_filter_never_emitted(self) -> None:
        # clip/filter are valid ops but v1 enumeration never emits them.
        req = parse_requirement({"name": "x", "transformations_allowed": ["clip", "filter"]})
        result = classify_requirement(req, _inventory(_record()))
        assert result.state == AvailabilityState.AVAILABLE  # no CRP/field gap at all
        req2 = parse_requirement(
            {"name": "x", "crs": {"authid": "EPSG:3857"}, "transformations_allowed": ["clip", "filter"]}
        )
        result2 = classify_requirement(req2, _inventory(_record()))
        assert result2.state == AvailabilityState.MISSING
        assert result2.missing_reason == MissingReason.CRS_GAP

    def test_transform_exceeds_bounds_cutoff(self) -> None:
        req = parse_requirement({"name": "x", "crs": {"authid": "EPSG:3857"}})
        result = classify_requirement(req, _inventory(_record()), max_chain_steps=0)
        assert result.state == AvailabilityState.MISSING
        assert result.missing_reason == MissingReason.TRANSFORM_EXCEEDS_BOUNDS

    def test_join_ignores_geometry_mismatch(self) -> None:
        # Two Point layers cannot join into a Polygon requirement.
        req = parse_requirement({"name": "x", "geometry": "Polygon", "required_fields": ["a", "b"]})
        left = _record("a", geometry_type="Point", fields=(LayerField("id", "Int"), LayerField("a", "String")))
        right = _record("b", geometry_type="Point", fields=(LayerField("id", "Int"), LayerField("b", "String")))
        result = classify_requirement(req, _inventory(left, right))
        assert result.state == AvailabilityState.MISSING
        assert result.chain == ()

    def test_join_ignores_crs_mismatch(self) -> None:
        req = parse_requirement({"name": "x", "required_fields": ["a", "b"], "crs": {"authid": "EPSG:3857"}})
        left = _record(
            "a",
            crs_authid="EPSG:4326",
            fields=(LayerField("id", "Int"), LayerField("a", "String")),
        )
        right = _record(
            "b",
            crs_authid="EPSG:4326",
            fields=(LayerField("id", "Int"), LayerField("b", "String")),
        )
        result = classify_requirement(req, _inventory(left, right))
        assert result.state == AvailabilityState.MISSING
        assert all(step.op != "join" for step in result.chain)

    def test_reproject_raster_never_for_vector_need(self) -> None:
        # Point requirement on a Point layer with CRS mismatch needs
        # reproject-vector, never reproject-raster.
        req = parse_requirement({"name": "x", "geometry": "Point", "crs": {"authid": "EPSG:3857"}})
        result = classify_requirement(req, _inventory(_record()))
        assert result.state == AvailabilityState.DERIVABLE
        assert result.chain[0].op == "reproject-vector"

    def test_reproject_raster_emitted(self) -> None:
        req = parse_requirement({"name": "x", "geometry": "Raster", "crs": {"authid": "EPSG:3857"}})
        rec = _record(geometry_type="Raster", provider="gdal", fields=(), crs_authid="EPSG:4326")
        result = classify_requirement(req, _inventory(rec))
        assert result.state == AvailabilityState.DERIVABLE
        assert result.chain[0].op == "reproject-raster"

    def test_vector_to_raster_emitted(self) -> None:
        req = parse_requirement({"name": "x", "geometry": "Raster"})
        result = classify_requirement(req, _inventory(_record()))
        assert result.state == AvailabilityState.DERIVABLE
        assert result.chain[0].op == "vector-to-raster"

    def test_conversion_blocked_by_crs_mismatch(self) -> None:
        req = parse_requirement({"name": "x", "geometry": "Point", "crs": {"authid": "EPSG:3857"}})
        rec = _record(geometry_type="Raster", provider="gdal", fields=(), crs_authid="EPSG:4326")
        result = classify_requirement(req, _inventory(rec))
        assert result.state == AvailabilityState.MISSING
        assert result.chain == ()

    def test_join_key_normalized(self) -> None:
        # lowercase provider key types still join via normalization.
        req = parse_requirement({"name": "x", "required_fields": ["zip", "area"]})
        left = _record("a", fields=(LayerField("id", "integer"), LayerField("zip", "string")))
        right = _record("b", fields=(LayerField("id", "integer"), LayerField("area", "double")))
        result = classify_requirement(req, _inventory(left, right))
        assert result.state == AvailabilityState.DERIVABLE
        assert dict(result.chain[0].params)["key"] == "id"


# ===========================================================================
# Classification — temporal, sources, threshold enforcement
# ===========================================================================


@pytest.mark.unit
class TestRequirementDimensions:
    def test_temporal_mismatch_is_no_layer(self) -> None:
        req = parse_requirement({"name": "x", "temporal": {"has_time": True}})
        result = classify_requirement(req, _inventory(_record(has_time=False)))
        assert result.state == AvailabilityState.MISSING
        assert result.missing_reason == MissingReason.NO_LAYER

    def test_temporal_match_passes(self) -> None:
        req = parse_requirement({"name": "x", "temporal": {"has_time": False}})
        result = classify_requirement(req, _inventory(_record(has_time=False)))
        assert result.state == AvailabilityState.AVAILABLE

    def test_temporal_unknown_is_deferred(self) -> None:
        req = parse_requirement({"name": "x", "temporal": {"has_time": True}})
        result = classify_requirement(req, _inventory(_record(has_time=None)))
        assert result.state == AvailabilityState.MISSING
        assert result.missing_reason == MissingReason.UNKNOWN_DEFERRED

    def test_sources_without_local_project(self) -> None:
        req = parse_requirement({"name": "x", "acceptable_sources": ["provider:stac.earth-search"]})
        result = classify_requirement(req, _inventory(_record()))
        assert result.state == AvailabilityState.MISSING
        assert result.missing_reason == MissingReason.NO_LAYER
        assert result.evidence == ()

    def test_threshold_below_one_partial_is_deferred(self) -> None:
        req = parse_requirement(
            {
                "name": "x",
                "extent": {"xmin": 0.0, "ymin": 0.0, "xmax": 20.0, "ymax": 20.0, "crs_authid": "EPSG:4326"},
                "coverage_threshold": 0.5,
            }
        )
        result = classify_requirement(req, _inventory(_record()))
        # ratio unverifiable QGIS-free: deferred, never a pass, never a gap claim.
        assert result.state == AvailabilityState.MISSING
        assert result.missing_reason == MissingReason.UNKNOWN_DEFERRED

    def test_temporal_mismatch_blocks_chain(self) -> None:
        # temporal gap cannot be repaired by reproject: no DERIVABLE.
        req = parse_requirement(
            {
                "name": "x",
                "crs": {"authid": "EPSG:3857"},
                "temporal": {"has_time": True},
            }
        )
        rec = _record(has_time=False)
        result = classify_requirement(req, _inventory(rec))
        assert result.state == AvailabilityState.MISSING
        assert result.chain == ()

    def test_temporal_unknown_blocks_chain(self) -> None:
        req = parse_requirement(
            {
                "name": "x",
                "crs": {"authid": "EPSG:3857"},
                "temporal": {"has_time": True},
            }
        )
        rec = _record(has_time=None)
        result = classify_requirement(req, _inventory(rec))
        assert result.state == AvailabilityState.MISSING
        assert result.chain == ()

    def test_v1_reason_subset_pinned(self) -> None:
        # Acquisition-scope reasons are never emitted by the v1 classifier.
        assert "provider-offline" not in [r.value for r in MissingReason]
        assert "license-unavailable" not in [r.value for r in MissingReason]
        assert len(MissingReason) == 8


# ===========================================================================
# Classification — MISSING taxonomy
# ===========================================================================


@pytest.mark.unit
class TestMissing:
    def test_empty_inventory(self) -> None:
        req = parse_requirement({"name": "x"})
        result = classify_requirement(req, _inventory())
        assert result.state == AvailabilityState.MISSING
        assert result.missing_reason == MissingReason.NO_LAYER

    def test_truncated_never_no_layer(self) -> None:
        req = parse_requirement({"name": "x", "geometry": "Polygon"})
        rec = _record(geometry_type="Point")
        result = classify_requirement(req, _inventory(rec, truncated=True))
        assert result.state == AvailabilityState.MISSING
        assert result.missing_reason == MissingReason.TRUNCATED_INVENTORY
        assert result.snapshot_truncated is True

    def test_schema_gap_names_missing(self) -> None:
        req = parse_requirement({"name": "x", "required_fields": ["nope"]})
        result = classify_requirement(req, _inventory(_record()))
        assert result.missing_reason == MissingReason.SCHEMA_GAP

    def test_best_candidate_evidence_order(self) -> None:
        req = parse_requirement({"name": "x", "geometry": "Polygon", "required_fields": ["zzz"]})
        a = _record("a", geometry_type="Point")
        b = _record("b", geometry_type="Polygon")
        result = classify_requirement(req, _inventory(a, b))
        # b passes geometry then fails fields; a fails geometry first.
        assert result.missing_reason == MissingReason.SCHEMA_GAP
        assert result.layer_id == "b"


# ===========================================================================
# Import guard: contracts.py is QGIS-free (M3-T03-F1 lesson)
# ===========================================================================


@pytest.mark.unit
class TestImportGuard:
    def test_no_qgis_imports_in_source(self) -> None:
        import pathlib

        source = pathlib.Path(contracts_module.__file__).read_text(encoding="utf-8")
        assert "import qgis" not in source
        assert "from qgis" not in source
        assert "from lunar_gis.project" not in source
        assert "from lunar_gis.data" not in source
        assert "import lunar_gis" not in source

    def test_contracts_importable_with_qgis_blocked(self) -> None:
        import importlib
        import sys

        blocked = sys.modules.get("qgis")
        sys.modules["qgis"] = None  # type: ignore[assignment]
        original = sys.modules.get("lunar_gis.data.contracts")
        try:
            for module in [m for m in list(sys.modules) if m.startswith("lunar_gis.data.contracts")]:
                del sys.modules[module]
            reloaded = importlib.import_module("lunar_gis.data.contracts")
            assert reloaded.AvailabilityState.AVAILABLE.value == "available"
        finally:
            if blocked is not None:
                sys.modules["qgis"] = blocked
            else:
                sys.modules.pop("qgis", None)
            # Restore the original module object so cross-module isinstance
            # checks keep working for the rest of the session.
            if original is not None:
                sys.modules["lunar_gis.data.contracts"] = original
