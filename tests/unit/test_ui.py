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
        assert plan["executed"] == []


class TestAssistantLoop:
    def _ahp_call(self) -> dict:
        return {
            "tool_name": "analysis.ahp",
            "tool_version": "1.0.0",
            "arguments": {"criteria": ["a", "b"], "matrix": [[1, 2], [0.5, 1]]},
        }

    def test_loop_executes_and_feeds_back(self, monkeypatch) -> None:
        from lunar_gis.ai import openrouter as openrouter_module

        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        calls = {"n": 0}

        def fake_chat(messages, config, api_key=None, tools=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return True, {
                    "choices": [
                        {
                            "message": {
                                "content": "Computing weights.",
                                "tool_calls": [
                                    {
                                        "function": {
                                            "name": "analysis_ahp",
                                            "arguments": '{"criteria": ["a", "b"], "matrix": [[1, 2], [0.5, 1]]}',
                                        }
                                    }
                                ],
                            }
                        }
                    ],
                }
            return True, {"choices": [{"message": {"content": "Weights computed.", "tool_calls": []}}]}

        monkeypatch.setattr(openrouter_module, "chat_completion", fake_chat)
        plan = plan_request("weight criteria", build_registry(), max_rounds=2)
        assert plan["ok"] is True
        assert calls["n"] == 2
        assert len(plan["executed"]) == 1
        assert plan["executed"][0]["tool_name"] == "analysis.ahp"
        assert plan["executed"][0]["ok"] is True
        assert plan["explanation"] == "Weights computed."
        assert plan["tool_calls"] == []

    def test_high_risk_never_auto_executed(self, monkeypatch) -> None:
        from lunar_gis.ai import openrouter as openrouter_module

        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        def fake_chat(messages, config, api_key=None, tools=None):
            _ = (messages, config, api_key, tools)
            return True, {
                "choices": [
                    {
                        "message": {
                            "content": "Downloading.",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "data_download_dataset",
                                        "arguments": '{"provider_id": "p", "dataset_id": "d", "asset_id": "a"}',
                                    }
                                }
                            ],
                        }
                    }
                ],
            }

        monkeypatch.setattr(openrouter_module, "chat_completion", fake_chat)
        plan = plan_request("download it", build_registry(), max_rounds=2)
        assert plan["ok"] is True
        assert plan["executed"] == []
        assert len(plan["tool_calls"]) == 1
        assert plan["tool_calls"][0]["tool_name"] == "data.download_dataset"

    def test_invalid_calls_skipped(self, monkeypatch) -> None:
        from lunar_gis.ai import openrouter as openrouter_module

        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        def fake_chat(messages, config, api_key=None, tools=None):
            _ = (messages, config, api_key, tools)
            return True, {
                "choices": [
                    {
                        "message": {
                            "content": "Done.",
                            "tool_calls": [{"function": {"name": "evil_run", "arguments": "{}"}}],
                        }
                    }
                ],
            }

        monkeypatch.setattr(openrouter_module, "chat_completion", fake_chat)
        plan = plan_request("do evil", build_registry(), max_rounds=1)
        # Unmapped model output fails closed at parse time (MALFORMED is a
        # hard error, never an offline fallback and never executed).
        assert plan["ok"] is False
        assert "MALFORMED_TOOL_CALL" in plan["error"]
        assert plan["executed"] == []

    def test_empty_explanation_narrated(self, monkeypatch) -> None:
        from lunar_gis.ai import openrouter as openrouter_module

        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        def fake_chat(messages, config, api_key=None, tools=None):
            return True, {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "analysis_ahp",
                                        "arguments": '{"criteria": ["a", "b"], "matrix": [[1, 2], [0.5, 1]]}',
                                    }
                                }
                            ],
                        }
                    }
                ],
            }

        monkeypatch.setattr(openrouter_module, "chat_completion", fake_chat)
        plan = plan_request("weight it", build_registry(), max_rounds=1)
        assert plan["ok"] is True
        assert plan["explanation"] != ""
        assert "analysis.ahp" in plan["explanation"]

    def test_assistant_executor_policy(self) -> None:
        from lunar_gis.ui.controller import create_assistant_executor, run_tool

        registry = build_registry()
        executor = create_assistant_executor(registry)
        context = default_context()
        good = run_tool(
            executor,
            "analysis.ahp",
            {"criteria": ["a", "b"], "matrix": [[1, 2], [0.5, 1]]},
            context,
        )
        assert good["ok"] is True
        gated = run_tool(
            executor,
            "data.download_dataset",
            {"provider_id": "p", "dataset_id": "d", "asset_id": "a"},
            context,
        )
        assert gated["ok"] is False
        assert "confirmation" in (gated["error"] or "").lower()


class TestHistory:
    def test_labels_and_cap(self) -> None:
        from lunar_gis.ui.controller import history_segments

        history = [{"role": "user", "text": f"q{i}"} for i in range(10)]
        segments = history_segments(history)
        assert len(segments) == 6
        assert segments[0].label.value == "trusted-user"
        mixed = history_segments([{"role": "user", "text": "hi"}, {"role": "assistant", "text": "hello there"}])
        assert [s.label.value for s in mixed] == ["trusted-user", "assistant-history"]

    def test_empty_history(self) -> None:
        from lunar_gis.ui.controller import history_segments

        assert history_segments(None) == []
        assert history_segments([]) == []


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
