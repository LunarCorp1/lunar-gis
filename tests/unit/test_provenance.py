"""Unit tests for M4-T06 provenance records + audit store."""

from __future__ import annotations

import pytest

from lunar_gis.provenance import records as records_module
from lunar_gis.provenance.records import (
    ProvenanceStatus,
    ProvenanceToolInvocation,
    ProvenanceTransformStep,
    ProvenanceValidation,
    make_record,
    provenance_canonical_json,
    provenance_identity,
    provenance_to_dict,
    strip_source_url,
    validate_provenance,
)
from lunar_gis.provenance.store import ProvenanceStore


def _record(**overrides) -> object:
    base: dict = {
        "subject_kind": "layer-ref",
        "subject_ref": "lid-1",
        "origin_kind": "project",
        "license_spdx": "NONE-declared",
        "retrieved_at": "2026-09-21T00:00:00+00:00",
    }
    base.update(overrides)
    return make_record(**base)


class TestStripSourceUrl:
    def test_strips_query(self) -> None:
        assert strip_source_url("https://example.com/data/x.tif?foo=bar") == "https://example.com/data/x.tif"

    def test_rejects_signed(self) -> None:
        assert strip_source_url("https://blob.example.com/x.tif?sig=abc&se=123") is None
        assert strip_source_url("https://blob.example.com/x.tif?token=abc") is None

    def test_rejects_non_http(self) -> None:
        assert strip_source_url("ftp://example.com/x") is None
        assert strip_source_url("/local/path") is None
        assert strip_source_url("") is None


class TestValidation:
    def test_valid_original(self) -> None:
        assert validate_provenance(_record()) == []

    def test_derived_requires_transforms(self) -> None:
        with pytest.raises(ValueError):
            make_record(
                subject_kind="file",
                subject_ref="out.gpkg",
                origin_kind="project",
                license_spdx="NONE-declared",
                retrieved_at="2026-09-21T00:00:00+00:00",
                status=ProvenanceStatus.DERIVED,
            )

    def test_derived_with_chain(self) -> None:
        rec = make_record(
            subject_kind="file",
            subject_ref="out.gpkg",
            origin_kind="project",
            license_spdx="NONE-declared",
            retrieved_at="2026-09-21T00:00:00+00:00",
            status=ProvenanceStatus.DERIVED,
            transforms=(ProvenanceTransformStep(op="clip", op_version="1.0", output_ref="out.gpkg"),),
        )
        assert validate_provenance(rec) == []

    def test_original_rejects_chain(self) -> None:
        with pytest.raises(ValueError):
            _record(
                transforms=(ProvenanceTransformStep(op="clip", op_version="1.0"),),
            )

    def test_provider_origin_requires_ids(self) -> None:
        with pytest.raises(ValueError):
            _record(origin_kind="provider")

    def test_bad_sha(self) -> None:
        with pytest.raises(ValueError):
            _record(sha256="xyz")

    def test_signed_source_url_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(source_url="https://blob.example.com/x.tif?sig=abc")

    def test_unstripped_source_url_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(source_url="https://example.com/x.tif?a=b")

    def test_empty_license_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(license_spdx="")


class TestIdentity:
    def test_stable_identity(self) -> None:
        assert provenance_identity(_record()) == provenance_identity(_record())

    def test_retrieved_at_excluded(self) -> None:
        a = _record(retrieved_at="2026-09-21T00:00:00+00:00")
        b = _record(retrieved_at="2026-09-22T00:00:00+00:00")
        assert provenance_identity(a) == provenance_identity(b)
        assert provenance_canonical_json(a) != provenance_canonical_json(b)

    def test_content_change_breaks_identity(self) -> None:
        a = _record()
        b = _record(subject_ref="lid-2")
        assert provenance_identity(a) != provenance_identity(b)

    def test_dict_omits_nones(self) -> None:
        payload = provenance_to_dict(_record())
        assert "source_url" not in payload
        assert payload["license"]["spdx"] == "NONE-declared"


class TestStore:
    def test_append_and_get(self) -> None:
        store = ProvenanceStore()
        rec = _record()
        identity = store.append(rec)
        assert store.get(identity) == rec
        assert store.count() == 1

    def test_idempotent_append(self) -> None:
        store = ProvenanceStore()
        identity = store.append(_record())
        assert store.append(_record()) == identity
        assert store.count() == 1

    def test_rejects_invalid(self) -> None:
        import dataclasses

        store = ProvenanceStore()
        rec = _record()
        bad = dataclasses.replace(rec, subject=dataclasses.replace(rec.subject, ref=""))
        with pytest.raises(ValueError):
            store.append(bad)

    def test_queries(self) -> None:
        store = ProvenanceStore()
        rec = _record(
            tool_invocations=(ProvenanceToolInvocation(tool_name="data.run_transformation", tool_version="1.0.0"),),
            requirement_ref="req-1",
        )
        store.append(rec)
        assert len(store.by_subject("lid-1")) == 1
        assert len(store.by_tool("data.run_transformation")) == 1
        assert len(store.by_tool("other")) == 0
        assert len(store.by_requirement("req-1")) == 1

    def test_lineage(self) -> None:
        store = ProvenanceStore()
        identity = store.append(
            _record(
                status=ProvenanceStatus.DERIVED,
                transforms=(ProvenanceTransformStep(op="clip", op_version="1.0", output_ref="o"),),
                validation=ProvenanceValidation(verdict="VALID", report_ref="abc"),
            )
        )
        chain = store.lineage(identity)
        assert chain["found"] is True
        assert chain["status"] == "DERIVED"
        assert chain["transforms"][0]["op"] == "clip"
        assert store.lineage("missing")["found"] is False

    def test_jsonl_roundtrip(self, tmp_path) -> None:
        path = str(tmp_path / "audit.jsonl")
        store = ProvenanceStore(jsonl_path=path)
        identity = store.append(_record())
        assert store.count() == 1
        reloaded = ProvenanceStore(jsonl_path=path)
        assert reloaded.count() == 1
        assert reloaded.get(identity) is not None


class TestImportBoundary:
    def test_no_forbidden_imports(self) -> None:
        import pathlib

        text = pathlib.Path(records_module.__file__).read_text(encoding="utf-8")
        assert "import qgis" not in text
        for banned in ("subprocess", "pickle"):
            assert banned not in text
