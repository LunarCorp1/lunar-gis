"""Unit tests for M8 reproducible reports."""

from __future__ import annotations

from lunar_gis.agent.registry import ToolRegistry
from lunar_gis.reports import html as html_module
from lunar_gis.reports import models as models_module
from lunar_gis.reports.html import render_html
from lunar_gis.reports.models import (
    ReportEnvelope,
    ReportModel,
    content_canonical_json,
    content_identity,
    make_content,
)
from lunar_gis.reports.report_tools import (
    export_handler,
    generate_handler,
    register_report_tools,
)


def _model(**overrides) -> ReportModel:
    content = make_content("Suitability", "find clinic sites", **overrides)
    return ReportModel(content=content, envelope=ReportEnvelope(generated_at="2026-09-21T00:00:00+00:00"))


class TestIdentity:
    def test_stable(self) -> None:
        assert content_identity(_model().content) == content_identity(_model().content)

    def test_envelope_excluded(self) -> None:
        first = ReportModel(content=_model().content, envelope=ReportEnvelope(generated_at="2026-01-01T00:00:00+00:00"))
        second = ReportModel(
            content=_model().content, envelope=ReportEnvelope(generated_at="2026-12-31T00:00:00+00:00")
        )
        assert content_identity(first.content) == content_identity(second.content)

    def test_content_change_breaks(self) -> None:
        assert content_identity(_model().content) != content_identity(_model(warnings=("w",)).content)

    def test_canonical_sorted(self) -> None:
        assert '"assumptions"' in content_canonical_json(_model().content)


class TestRender:
    def test_full_report(self) -> None:
        model = _model(
            requirements=({"name": "r", "geometry": "Point", "required_fields": []},),
            data_used=({"ref": "a", "kind": "layer-ref", "validation": "VALID"},),
            missing_data=({"name": "r2", "reason": "no-layer"},),
            transformations=({"op": "clip", "output_ref": "o"},),
            analysis=({"title": "AHP", "weights": {"a": 0.6, "b": 0.4}, "cr": 0.01, "consistency_flag": "consistent"},),
            results=({"summary": "site X wins"},),
            assumptions=("uniform costs",),
            warnings=("partial validity",),
            provenance=({"subject_ref": "a", "status": "ORIGINAL", "identity": "abc123"},),
            licenses=({"spdx": "ODbL-1.0", "attribution": "OSM"},),
            engine_versions={"ahp": "2.0.0"},
        )
        page = render_html(model)
        for needle in (
            "<h1>Suitability</h1>",
            "Data requirements",
            "Missing data",
            "Transformations",
            "Analysis",
            "Assumptions",
            "Warnings",
            "Provenance",
            "Licenses",
            "Reproducibility",
            'role="img"',
            "text alternative",
            'scope="col"',
            'lang="en"',
        ):
            assert needle in page

    def test_escaping(self) -> None:
        model = _model(results=({"summary": '<script>alert("x")</script>'},))
        page = render_html(model)
        assert "<script>" not in page
        assert "&lt;script&gt;" in page

    def test_empty_sections_omitted(self) -> None:
        page = render_html(_model())
        assert "Missing data" not in page
        assert "Reproducibility" in page


class TestTools:
    def test_generate(self) -> None:
        result = generate_handler({"title": "T", "user_request": "do it", "sections": {"warnings": ("w",)}})
        assert result["ok"] is True
        assert result["identity"]
        assert "<html" in result["html"]

    def test_generate_invalid(self) -> None:
        assert generate_handler({"title": "", "user_request": "x"})["ok"] is False

    def test_export(self, tmp_path) -> None:
        result = export_handler(
            {
                "title": "T",
                "user_request": "do it",
                "output_relpath": "report.html",
                "workspace_dir": str(tmp_path),
            }
        )
        assert result["ok"] is True
        assert (tmp_path / "report.html").exists()

    def test_export_traversal(self, tmp_path) -> None:
        result = export_handler(
            {"title": "T", "user_request": "x", "output_relpath": "../../evil.html", "workspace_dir": str(tmp_path)}
        )
        assert result["ok"] is False

    def test_register(self) -> None:
        registry = ToolRegistry()
        register_report_tools(registry)
        assert registry.has("reports.generate")
        assert registry.has("reports.export")


class TestImportBoundary:
    def test_no_qgis(self) -> None:
        import pathlib

        for module in (models_module, html_module):
            text = pathlib.Path(module.__file__).read_text(encoding="utf-8")
            assert "import qgis" not in text
