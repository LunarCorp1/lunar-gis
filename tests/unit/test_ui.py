"""Unit tests for M9 UI controller (offline) + workspace (qgis-marked)."""

from __future__ import annotations

import pytest

from lunar_gis.agent.registry import ToolRegistry
from lunar_gis.ui import controller as controller_module
from lunar_gis.ui.controller import (
    ai_status,
    build_registry,
    confirmation_text,
    create_executor,
    default_context,
    make_confirmation,
    plan_request,
    run_tool,
)


class TestRegistryWiring:
    def test_all_tools_registered(self) -> None:
        registry = build_registry()
        for name in (
            "analysis.ahp",
            "analysis.ahp_sensitivity",
            "analysis.buffer",
            "analysis.intersection",
            "analysis.dissolve",
            "analysis.zonal_statistics",
            "analysis.spatial_join",
            "data.describe_project",
            "data.check_requirement",
            "data.validate_dataset",
            "data.register_local_file",
            "data.search_catalog",
            "data.download_dataset",
            "data.run_transformation",
            "cartography.style_layer",
            "cartography.create_layout",
            "cartography.export_map",
            "reports.generate",
            "reports.export",
        ):
            assert registry.has(name), name

    def test_run_tool_offline(self) -> None:
        registry = build_registry()
        executor = create_executor(registry)
        result = run_tool(
            executor,
            "analysis.ahp",
            {"criteria": ["a", "b"], "matrix": [[1, 2], [0.5, 1]]},
            default_context(),
        )
        assert result["ok"] is True

    def test_run_tool_unknown(self) -> None:
        registry = build_registry()
        result = run_tool(create_executor(registry), "nope.missing", {}, default_context())
        assert result["ok"] is False


class TestConfirmation:
    def test_high_risk_text(self) -> None:
        registry = build_registry()
        info = confirmation_text(
            "data.download_dataset", {"provider_id": "p", "dataset_id": "d", "asset_id": "a"}, registry
        )
        assert info["ok"] is True
        assert "Confirm data.download_dataset" in info["title"]
        assert "Risks" in info["body"]

    def test_unknown_tool(self) -> None:
        assert confirmation_text("nope.missing", {}, ToolRegistry())["ok"] is False

    def test_artifact_scoped(self) -> None:
        registry = build_registry()
        context = default_context()
        artifact = make_confirmation("data.describe_project", {}, context, registry)
        assert artifact is not None
        assert artifact.tool_name == "data.describe_project"
        assert make_confirmation("nope.missing", {}, context, registry) is None


class TestAiStatus:
    def test_offline_without_key(self, monkeypatch) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        status = ai_status()
        assert status["offline_capable"] is True
        assert status["mode"] in ("ai-assisted", "offline-deterministic")


class TestPlan:
    def test_offline_plan(self, monkeypatch) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        plan = plan_request("find clinics", build_registry())
        assert plan["ok"] is True
        assert plan["requirement"] is not None


class TestImportBoundary:
    def test_controller_qgis_free(self) -> None:
        import pathlib

        text = pathlib.Path(controller_module.__file__).read_text(encoding="utf-8")
        assert "import qgis" not in text
        assert "from qgis" not in text


@pytest.mark.qgis
class TestWorkspaceConstruction:
    def test_workspace_builds(self) -> None:
        pytest.importorskip("qgis.PyQt.QtWidgets")
        from qgis.PyQt.QtWidgets import QApplication  # type: ignore[import-not-found]

        app = QApplication.instance() or QApplication([])
        _ = app
        from lunar_gis.ui.workspace import LunarGISWorkspace

        workspace = LunarGISWorkspace()
        assert workspace.tabs.count() == 8
        labels = [workspace.tabs.tabText(i) for i in range(workspace.tabs.count())]
        assert labels == ["Assistant", "Project", "Data", "Analysis", "Results", "Provenance", "Reports", "Settings"]
