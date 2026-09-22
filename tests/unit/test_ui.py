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
            "analysis.suitability",
            "data.describe_project",
            "data.check_requirement",
            "data.validate_dataset",
            "data.register_local_file",
            "data.load_into_project",
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

    def test_run_tool_high_risk_requires_confirmation(self) -> None:
        from lunar_gis.ui.controller import run_tool

        registry = build_registry()
        result = run_tool(
            create_executor(registry),
            "data.download_dataset",
            {"provider_id": "p", "dataset_id": "d", "asset_id": "a"},
            default_context(),
        )
        assert result["ok"] is False

    def test_run_tool_unknown(self) -> None:
        registry = build_registry()
        result = run_tool(create_executor(registry), "nope.missing", {}, default_context())
        assert result["ok"] is False

    def test_run_tool_two_levels(self) -> None:
        from lunar_gis.agent.registry import ToolRegistry, ToolRisk, ToolSpec, ToolVersion
        from lunar_gis.ui.controller import run_tool

        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="test.domain_tool",
                version=ToolVersion(1, 0, 0),
                risk=ToolRisk.LOW,
                handler=lambda data: {"ok": False, "error": "domain bad"},
            )
        )
        result = run_tool(create_executor(registry), "test.domain_tool", {}, default_context())
        assert result["ok"] is True
        assert result["handler_ok"] is False
        assert result["handler_error"] == "domain bad"


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

    def test_three_round_chain(self, monkeypatch) -> None:
        from lunar_gis.ai import openrouter as openrouter_module

        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        calls = {"n": 0}

        def fake_chat(messages, config, api_key=None, tools=None):
            calls["n"] += 1
            if calls["n"] == 1:
                content, tool = "Step one.", "analysis_ahp"
            elif calls["n"] == 2:
                content, tool = "Step two.", "analysis_ahp_sensitivity"
            else:
                content, tool = "All done.", None
            message: dict = {"content": content, "tool_calls": []}
            if tool is not None:
                args = '{"criteria": ["a", "b"], "matrix": [[1, 2], [0.5, 1]]}'
                message["tool_calls"] = [{"function": {"name": tool, "arguments": args}}]
            return True, {"choices": [{"message": message}]}

        monkeypatch.setattr(openrouter_module, "chat_completion", fake_chat)
        plan = plan_request("chain it", build_registry(), max_rounds=3)
        assert plan["ok"] is True
        assert calls["n"] == 3
        assert [e["tool_name"] for e in plan["executed"]] == ["analysis.ahp", "analysis.ahp_sensitivity"]
        assert plan["explanation"] == "All done."

    def test_loop_marks_handler_failure(self, monkeypatch) -> None:
        from lunar_gis.ai import openrouter as openrouter_module

        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        def fake_chat(messages, config, api_key=None, tools=None):
            return True, {
                "choices": [
                    {
                        "message": {
                            "content": "Searching.",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "data_search_catalog",
                                        "arguments": '{"provider_id": "osm.overpass"}',
                                    }
                                }
                            ],
                        }
                    }
                ],
            }

        monkeypatch.setattr(openrouter_module, "chat_completion", fake_chat)
        plan = plan_request("search hospitals", build_registry(), max_rounds=1)
        assert plan["ok"] is True
        assert len(plan["executed"]) == 1
        assert plan["executed"][0]["ok"] is False
        assert "failed" in plan["executed"][0]["summary"]

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


class TestEvidenceFeedback:
    def test_segment_carries_summary(self) -> None:
        from lunar_gis.ai.context import engine_output_segment

        segment = engine_output_segment("data.describe_project", {"ok": True, "summary": "layers: roads"})
        assert "layers: roads" in segment.text
        assert segment.label.value == "engine-output"

    def test_narration_empty_project(self) -> None:
        from lunar_gis.ui.controller import _narrate_executed

        text = _narrate_executed(
            [
                {
                    "tool_name": "data.describe_project",
                    "ok": True,
                    "summary": 'data.describe_project: {"ok": true, "records": []}',
                }
            ]
        )
        assert "no layers" in text

    def test_narration_with_layers(self) -> None:
        import json

        from lunar_gis.ui.controller import _narrate_executed

        payload = {"ok": True, "records": [{"name": "roads", "geometry_type": "1", "feature_count": 5}]}
        text = _narrate_executed(
            [
                {
                    "tool_name": "data.describe_project",
                    "ok": True,
                    "summary": "data.describe_project: " + json.dumps(payload),
                }
            ]
        )
        assert "roads" in text
        assert "1 layers" in text or "(1)" in text

    def test_narration_check_and_search(self) -> None:
        import json

        from lunar_gis.ui.controller import _narrate_executed

        check = {"ok": True, "availability": "missing", "fulfillment_kind": "missing", "missing_reason": "no-layer"}
        search = {"ok": True, "total": 1, "results": [{"title": "Hospitals"}]}
        text = _narrate_executed(
            [
                {
                    "tool_name": "data.check_requirement",
                    "ok": True,
                    "summary": "data.check_requirement: " + json.dumps(check),
                },
                {
                    "tool_name": "data.search_catalog",
                    "ok": True,
                    "summary": "data.search_catalog: " + json.dumps(search),
                },
            ]
        )
        assert "missing" in text
        assert "Hospitals" in text

    def test_round_two_gets_nudge(self, monkeypatch) -> None:
        from lunar_gis.ai import openrouter as openrouter_module

        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        seen_messages: list = []

        def fake_chat(messages, config, api_key=None, tools=None):
            seen_messages.append(messages)
            if len(seen_messages) == 1:
                return True, {
                    "choices": [
                        {
                            "message": {
                                "content": "Computing.",
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
            return True, {"choices": [{"message": {"content": "Done.", "tool_calls": []}}]}

        monkeypatch.setattr(openrouter_module, "chat_completion", fake_chat)
        plan = plan_request("weight it", build_registry(), max_rounds=2)
        assert plan["ok"] is True
        assert len(seen_messages) == 2
        round_two_text = seen_messages[1][1]["content"]
        assert "engine-output" in round_two_text
        assert "weights" in round_two_text or "analysis" in round_two_text
        assert "trusted-system" in round_two_text

    def test_block_only_explanation_narrated(self, monkeypatch) -> None:
        from lunar_gis.ai import openrouter as openrouter_module

        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        def fake_chat(messages, config, api_key=None, tools=None):
            args = '{"criteria": ["a", "b"], "matrix": [[1, 2], [0.5, 1]]}'
            return True, {
                "choices": [
                    {
                        "message": {
                            "content": '```json {"tool": "analysis.ahp", "arguments": ' + args + "} ```",
                            "tool_calls": [],
                        }
                    }
                ],
            }

        monkeypatch.setattr(openrouter_module, "chat_completion", fake_chat)
        plan = plan_request("weight it", build_registry(), max_rounds=1)
        assert plan["ok"] is True
        assert "```" not in plan["explanation"]
        assert "analysis.ahp" in plan["explanation"]

    def test_strip_machine_blocks(self) -> None:
        from lunar_gis.ui.controller import _strip_machine_blocks

        assert _strip_machine_blocks('hello\n```json {"a": 1} ```\nworld') == "hello\nworld"
        assert _strip_machine_blocks("plain text") == "plain text"
        assert _strip_machine_blocks('```json {"a": 1} ```') == ""

    def test_clean_display(self) -> None:
        from lunar_gis.ui.controller import clean_display

        # Model-echoed entities resolve once (display shows quotes)...
        assert "&amp;quot;" not in clean_display("a &quot;x&quot;")
        assert "x" in clean_display("a &quot;x&quot;")
        # ...twice-escaped entities resolve too (no "&amp;" residue)...
        assert "&amp;" not in clean_display("a &amp;quot;x&amp;quot;")
        assert "x" in clean_display("a &amp;quot;x&amp;quot;")
        # ...while real markup stays inert.
        assert "<script>" not in clean_display('<script>alert("x")</script>')
        assert "alert" in clean_display('<script>alert("x")</script>')

    def test_narration_failed_with_reason(self) -> None:
        from lunar_gis.ui.controller import _narrate_executed

        text = _narrate_executed(
            [{"tool_name": "data.search_catalog", "ok": False, "summary": "failed: PROVIDER_OFFLINE", "output": {}}]
        )
        assert "data.search_catalog failed" in text
        assert "PROVIDER_OFFLINE" in text

    def test_narration_structured_no_placeholders(self) -> None:
        from lunar_gis.ui.controller import _narrate_executed

        text = _narrate_executed(
            [
                {
                    "tool_name": "data.check_requirement",
                    "ok": True,
                    "summary": "s",
                    "output": {
                        "availability": "missing",
                        "fulfillment_kind": "missing",
                        "missing_reason": "no-layer",
                    },
                },
                {
                    "tool_name": "data.download_dataset",
                    "ok": True,
                    "summary": "s",
                    "output": {"size_bytes": 1234, "sha256": "abcdef1234567890", "sandbox_relpath": "f.tif"},
                },
                {
                    "tool_name": "data.load_into_project",
                    "ok": True,
                    "summary": "s",
                    "output": {"layer_id": "lid", "layer_name": "malawi"},
                },
            ]
        )
        assert "?" not in text
        assert "missing" in text
        assert "1234 bytes" in text
        assert "malawi" in text


class TestAffirmation:
    def test_yes_variants(self) -> None:
        from lunar_gis.ui.controller import is_affirmation

        for text in (
            "yes",
            "Yes",
            "YES!",
            "y",
            "proceed",
            "confirm",
            "do it",
            "go ahead",
            "ok",
            "download it",
            "yes, download it",
        ):
            assert is_affirmation(text) is True, text

    def test_non_affirmations(self) -> None:
        from lunar_gis.ui.controller import is_affirmation

        for text in ("", "maybe", "yesterday", "okra", "do search them", "create a map", "no"):
            assert is_affirmation(text) is False, text


class TestProgressState:
    def test_update_snapshot_cancel(self) -> None:
        from lunar_gis.ui.tasks import ProgressState

        state = ProgressState()
        assert state.cancelled() is False
        state.update(50, 100)
        snapshot = state.snapshot()
        assert snapshot["received"] == 50
        assert snapshot["total"] == 100
        assert snapshot["fraction"] == 0.5
        state.cancel()
        assert state.cancelled() is True
        assert state.snapshot()["cancelled"] is True

    def test_unknown_total(self) -> None:
        from lunar_gis.ui.tasks import ProgressState

        state = ProgressState()
        state.update(10, None)
        assert state.snapshot()["fraction"] is None

    def test_thread_safety_smoke(self) -> None:
        import threading

        from lunar_gis.ui.tasks import ProgressState

        state = ProgressState()

        def worker() -> None:
            for i in range(100):
                state.update(i, 100)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert state.snapshot()["received"] < 100

    def test_create_task_needs_qgis(self) -> None:
        import sys

        from lunar_gis.ui import tasks as tasks_module

        assert "qgis" not in sys.modules or sys.modules.get("qgis") is None
        with pytest.raises(ImportError):
            tasks_module.create_task("x", lambda: None)


@pytest.mark.qgis
class TestFunctionTask:
    def test_task_runs_offline_function(self) -> None:
        pytest.importorskip("qgis.core")
        from lunar_gis.ui.tasks import create_task

        task = create_task("demo", lambda a, b: a + b, 2, 3)
        assert task.run() is True


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
