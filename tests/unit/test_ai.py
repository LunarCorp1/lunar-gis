"""Unit tests for M5 AI layer (deterministic fixtures/mocks only).

No live LLM in CI: the OpenRouter transport is tested via shape
validation, key-redaction, endpoint pinning, and response parsing.
Planner tests use the offline path + mocked chat_completion.
"""

from __future__ import annotations

from lunar_gis.agent.execution import ControlledExecutor
from lunar_gis.agent.registry import ToolExecutionContext, ToolRegistry
from lunar_gis.ai import contracts as contracts_module
from lunar_gis.ai import openrouter as openrouter_module
from lunar_gis.ai.context import (
    build_messages,
    describe_context,
    engine_output_segment,
    escape_display,
    project_summary_segment,
    provider_segment,
)
from lunar_gis.ai.contracts import (
    AIConfig,
    ContextSegment,
    TrustLabel,
    validate_tool_call_shape,
)
from lunar_gis.ai.planner import heuristic_requirement, plan_offline, plan_with_ai
from lunar_gis.ai.toolcalling import (
    execute_validated_calls,
    registry_tool_schemas,
    validate_call_against_registry,
)
from lunar_gis.analysis.tools import register_ahp_tool


class TestToolCallShape:
    def test_valid(self) -> None:
        call = {"tool_name": "data.describe_project", "tool_version": "1.0.0", "arguments": {}}
        assert validate_tool_call_shape(call) == []

    def test_missing_name(self) -> None:
        assert validate_tool_call_shape({"arguments": {}}) != []

    def test_bad_name(self) -> None:
        assert validate_tool_call_shape({"tool_name": "nosuchtool", "arguments": {}}) != []

    def test_bad_version(self) -> None:
        call = {"tool_name": "a.b", "tool_version": "v1", "arguments": {}}
        assert validate_tool_call_shape(call) != []

    def test_non_dict(self) -> None:
        assert validate_tool_call_shape(["x"]) != []


class TestContext:
    def test_escape(self) -> None:
        assert escape_display('<script>alert("x")</script>') == "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;"

    def test_project_summary_labels_untrusted(self) -> None:
        payload = {
            "snapshot_id": "s",
            "taken_at": "t",
            "records": [
                {
                    "name": "<b>roads</b>",
                    "geometry_type": "0",
                    "crs_authid": "EPSG:4326",
                    "feature_count": 5,
                    "fields": [{"name": "id"}, {"name": "name"}],
                    "storage": "file",
                    "valid": True,
                }
            ],
        }
        segment = project_summary_segment(payload)
        assert segment.label == TrustLabel.UNTRUSTED_PROJECT
        assert "&lt;b&gt;" in segment.text
        assert "attribute" not in segment.text.lower() or "no attribute data" in segment.text

    def test_engine_segment(self) -> None:
        segment = engine_output_segment("check", {"availability": "available", "ok": True})
        assert segment.label == TrustLabel.ENGINE_OUTPUT

    def test_provider_segment_escapes(self) -> None:
        segment = provider_segment([{"title": "<img>", "dataset_id": "d", "license_spdx": "x"}])
        assert segment.label == TrustLabel.UNTRUSTED_PROVIDER
        assert "<img>" not in segment.text

    def test_build_messages_labels_inline(self) -> None:
        segments = [ContextSegment(label=TrustLabel.UNTRUSTED_PROJECT, text="hello")]
        messages = build_messages("sys", "do things", segments)
        assert messages[0]["role"] == "system"
        assert "[untrusted-project]" in messages[1]["content"]
        assert "[trusted-user]" in messages[1]["content"]

    def test_disclosure(self) -> None:
        segments = [ContextSegment(label=TrustLabel.ENGINE_OUTPUT, text="abc")]
        disclosure = describe_context(segments)
        assert disclosure["contains_api_keys"] is False
        assert disclosure["contains_geometry"] is False
        assert disclosure["total_chars"] == 3


class TestOpenRouter:
    def test_no_key_offline(self, monkeypatch) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        ok, payload = openrouter_module.chat_completion([{"role": "user", "content": "hi"}], AIConfig(), api_key=None)
        assert ok is False
        assert payload["error"] == "NO_API_KEY"

    def test_endpoint_pinned(self, monkeypatch) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        config = AIConfig(endpoint="https://evil.example.com/v1")
        ok, payload = openrouter_module.chat_completion([{"role": "user", "content": "hi"}], config)
        assert ok is False
        assert "allowlist" in payload["detail"]

    def test_parse_valid(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "content": "Here is the plan.",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "data.describe_project",
                                    "arguments": "{}",
                                }
                            }
                        ],
                    }
                }
            ]
        }
        ok, parsed = openrouter_module.parse_response(payload, model="m")
        assert ok is True
        assert parsed["explanation"] == "Here is the plan."
        assert parsed["tool_calls"][0]["tool_name"] == "data.describe_project"

    def test_parse_bad_arguments(self) -> None:
        payload = {"choices": [{"message": {"tool_calls": [{"function": {"name": "a.b", "arguments": "{bad"}}]}}]}
        ok, parsed = openrouter_module.parse_response(payload)
        assert ok is False
        assert parsed["error"] == "MALFORMED_TOOL_CALL"

    def test_key_resolution_env(self, monkeypatch) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
        assert openrouter_module.resolve_api_key() == "env-key"
        assert openrouter_module.has_api_key() is True

    def test_config_public_has_no_key(self) -> None:
        public = AIConfig().public_dict()
        assert "api_key" not in str(public).lower().replace("api_key_configured", "")


class TestToolCalling:
    def _registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        register_ahp_tool(registry)
        return registry

    def test_unknown_tool_rejected(self) -> None:
        ok, info = validate_call_against_registry(
            {"tool_name": "nope.missing", "tool_version": "1.0.0", "arguments": {}},
            self._registry(),
        )
        assert ok is False
        assert info["error"] == "UNKNOWN_TOOL"

    def test_version_mismatch_rejected(self) -> None:
        ok, info = validate_call_against_registry(
            {"tool_name": "analysis.ahp", "tool_version": "9.9.9", "arguments": {}},
            self._registry(),
        )
        assert ok is False
        assert info["error"] == "UNSUPPORTED_TOOL_VERSION"

    def test_bad_arguments_rejected(self) -> None:
        ok, info = validate_call_against_registry(
            {"tool_name": "analysis.ahp", "tool_version": "1.0.0", "arguments": {"nope": 1}},
            self._registry(),
        )
        assert ok is False

    def test_valid_call_executes(self) -> None:
        registry = self._registry()
        executor = ControlledExecutor(registry)
        context = ToolExecutionContext(session_id="t")
        results = execute_validated_calls(
            [
                {
                    "tool_name": "analysis.ahp",
                    "tool_version": "1.0.0",
                    "arguments": {"criteria": ["a", "b"], "matrix": [[1, 2], [0.5, 1]]},
                }
            ],
            registry,
            executor,
            context,
        )
        assert results[0]["ok"] is True

    def test_schemas_hide_handlers(self) -> None:
        schemas = registry_tool_schemas(self._registry())
        assert schemas[0]["name"] == "analysis.ahp"
        assert "handler" not in str(schemas)


class TestPlanner:
    def test_heuristic_geometry(self) -> None:
        assert heuristic_requirement("find clinics as points")["geometry"] == "Point"
        assert heuristic_requirement("suitability raster")["geometry"] == "Raster"
        assert heuristic_requirement("hello")["geometry"] == "Any"

    def test_offline_plan(self) -> None:
        result = plan_offline("find suitable clinic locations")
        assert result.ok is True
        assert result.requirement is not None
        assert result.tool_calls[0].tool_name == "data.describe_project"
        assert any("offline" in w for w in result.warnings)

    def test_plan_with_ai_no_key_falls_back(self, monkeypatch) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        result = plan_with_ai("hello", [], AIConfig(), api_key=None)
        assert result.ok is True
        assert any("no-api-key" in w for w in result.warnings)

    def test_plan_with_ai_mocked(self, monkeypatch) -> None:
        def fake_chat(messages, config, api_key=None, tools=None):
            _ = (messages, config, api_key, tools)
            return True, {
                "choices": [{"message": {"content": "Plan.", "tool_calls": []}}],
            }

        monkeypatch.setattr(openrouter_module, "chat_completion", fake_chat)
        result = plan_with_ai("hello", [], AIConfig(), api_key="k")
        assert result.ok is True
        assert result.explanation == "Plan."


class TestImportBoundary:
    def test_no_qgis_network_in_contracts(self) -> None:
        import pathlib

        text = pathlib.Path(contracts_module.__file__).read_text(encoding="utf-8")
        assert "import qgis" not in text
        for banned in ("subprocess", "socket"):
            assert banned not in text
