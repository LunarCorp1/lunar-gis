"""Unit tests for the OpenRouter provider integration fix.

All HTTP is mocked (no key, no network in CI): a fake opener seam
replaces ``_build_opener`` and DNS is stubbed. Covers the 15 required
behaviors: provider selection, settings-key consumption, request
construction, key confinement, success parsing, offline fallback,
auth/429/5xx/malformed handling, offline determinism, privacy,
governance, confirmation, and secret-freedom of records.
"""

from __future__ import annotations

import io
import json
import socket
import ssl
import sys
import types
import urllib.error

import pytest

from lunar_gis.ai import openrouter as openrouter_module
from lunar_gis.ai.contracts import AIConfig, OFFLINE_FALLBACK_ERRORS
from lunar_gis.ai.planner import plan_offline, plan_with_ai
from lunar_gis.ai.toolcalling import (
    build_provider_tools,
    from_provider_name,
    registry_tool_schemas,
    to_provider_name,
)

TEST_KEY = "test-key-xyz-123"


class FakeResponse:
    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body

    def read(self, size: int = -1) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class FakeOpener:
    """Captures the request; replays a scripted outcome."""

    def __init__(self, outcome: object):
        self.outcome = outcome
        self.requests: list = []

    def open(self, request: object, timeout: object = None) -> FakeResponse:
        self.requests.append(request)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def _install(monkeypatch: pytest.MonkeyPatch, outcome: object) -> FakeOpener:
    opener = FakeOpener(outcome)
    monkeypatch.setattr(openrouter_module, "_build_opener", lambda: opener)
    monkeypatch.setattr("lunar_gis.data.adapters.transport.resolve_and_check", lambda host: (True, "ok"))
    return opener


def _ok_body(explanation: str = "Hello from the model.") -> bytes:
    return json.dumps({"choices": [{"message": {"content": explanation, "tool_calls": []}}]}).encode()


def _http_error(code: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://openrouter.ai/api/v1/chat/completions", code, f"HTTP {code}", {}, io.BytesIO(body)
    )


class TestProviderSelection:
    def test_configured_key_reaches_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        opener = _install(monkeypatch, FakeResponse(200, _ok_body()))
        ok, payload = openrouter_module.chat_completion(
            [{"role": "user", "content": "hi"}], AIConfig(), api_key=TEST_KEY
        )
        assert ok is True
        assert len(opener.requests) == 1
        request = opener.requests[0]
        assert request.full_url == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["Authorization"] == f"Bearer {TEST_KEY}"
        body = json.loads(request.data.decode())
        assert body["model"] == "openai/gpt-4o-mini"
        assert body["messages"][0]["content"] == "hi"

    def test_planner_uses_ai_when_reachable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, FakeResponse(200, _ok_body("Real model answer.")))
        result = plan_with_ai("Hello", [], AIConfig(), api_key=TEST_KEY)
        assert result.ok is True
        assert result.explanation == "Real model answer."
        assert not any("offline-heuristic" in w for w in result.warnings)
        assert not any("ai-error" in w for w in result.warnings)


class TestSettingsKeyConsumption:
    def test_qsettings_round_trip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store: dict = {}

        class FakeQSettings:
            def __init__(self, org: str, app: str):
                self._key = (org, app)

            def value(self, name: str, default: object = "") -> object:
                return store.get((self._key, name), default)

            def setValue(self, name: str, value: object) -> None:
                store[(self._key, name)] = value

            def remove(self, name: str) -> None:
                store.pop((self._key, name), None)

        qtcore = types.ModuleType("QtCore")
        qtcore.QSettings = FakeQSettings
        pyqt = types.ModuleType("PyQt")
        pyqt.QtCore = qtcore
        qgis = types.ModuleType("qgis")
        qgis.PyQt = pyqt
        monkeypatch.setitem(sys.modules, "qgis", qgis)
        monkeypatch.setitem(sys.modules, "qgis.PyQt", pyqt)
        monkeypatch.setitem(sys.modules, "qgis.PyQt.QtCore", qtcore)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        assert openrouter_module.has_api_key() is False
        assert openrouter_module.store_api_key("settings-key-abc") is True
        assert openrouter_module.has_api_key() is True
        assert openrouter_module.resolve_api_key() == "settings-key-abc"
        opener = _install(monkeypatch, FakeResponse(200, _ok_body()))
        ok, _ = openrouter_module.chat_completion([{"role": "user", "content": "hi"}], AIConfig())
        assert ok is True
        assert opener.requests[0].headers["Authorization"] == "Bearer settings-key-abc"


class TestErrorClassification:
    def test_401_is_auth_failed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = json.dumps({"error": {"message": "Invalid API key"}}).encode()
        _install(monkeypatch, _http_error(401, body))
        ok, payload = openrouter_module.chat_completion(
            [{"role": "user", "content": "hi"}], AIConfig(), api_key=TEST_KEY
        )
        assert ok is False
        assert payload["error"] == "AUTH_FAILED"
        assert "Invalid API key" in payload["detail"]
        assert TEST_KEY not in payload["detail"]

    def test_403_is_auth_failed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, _http_error(403))
        ok, payload = openrouter_module.chat_completion(
            [{"role": "user", "content": "hi"}], AIConfig(), api_key=TEST_KEY
        )
        assert ok is False
        assert payload["error"] == "AUTH_FAILED"

    def test_404_is_endpoint_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, _http_error(404))
        ok, payload = openrouter_module.chat_completion(
            [{"role": "user", "content": "hi"}], AIConfig(), api_key=TEST_KEY
        )
        assert ok is False
        assert payload["error"] == "ENDPOINT_NOT_FOUND"

    def test_429_is_rate_limited(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, _http_error(429))
        ok, payload = openrouter_module.chat_completion(
            [{"role": "user", "content": "hi"}], AIConfig(), api_key=TEST_KEY
        )
        assert ok is False
        assert payload["error"] == "RATE_LIMITED"

    def test_500_is_server_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, _http_error(500))
        ok, payload = openrouter_module.chat_completion(
            [{"role": "user", "content": "hi"}], AIConfig(), api_key=TEST_KEY
        )
        assert ok is False
        assert payload["error"] == "SERVER_ERROR"

    def test_dns_failure_is_offline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, urllib.error.URLError(socket.gaierror("Name or service not known")))
        ok, payload = openrouter_module.chat_completion(
            [{"role": "user", "content": "hi"}], AIConfig(), api_key=TEST_KEY
        )
        assert ok is False
        assert payload["error"] == "PROVIDER_OFFLINE"
        assert "dns" in payload["detail"]

    def test_tls_failure_distinct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, urllib.error.URLError(ssl.SSLCertVerificationError("certificate verify failed")))
        ok, payload = openrouter_module.chat_completion(
            [{"role": "user", "content": "hi"}], AIConfig(), api_key=TEST_KEY
        )
        assert ok is False
        assert payload["error"] == "TLS_FAILED"

    def test_connection_refused_distinct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, urllib.error.URLError(ConnectionRefusedError("refused")))
        ok, payload = openrouter_module.chat_completion(
            [{"role": "user", "content": "hi"}], AIConfig(), api_key=TEST_KEY
        )
        assert ok is False
        assert payload["error"] == "NETWORK_UNREACHABLE"

    def test_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, TimeoutError("timed out"))
        ok, payload = openrouter_module.chat_completion(
            [{"role": "user", "content": "hi"}], AIConfig(), api_key=TEST_KEY
        )
        assert ok is False
        assert payload["error"] == "TIMEOUT"

    def test_malformed_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, FakeResponse(200, b"not json"))
        ok, payload = openrouter_module.chat_completion(
            [{"role": "user", "content": "hi"}], AIConfig(), api_key=TEST_KEY
        )
        assert ok is False
        assert payload["error"] == "INVALID_RESPONSE"


class TestFallbackPolicy:
    def test_offline_fallback_for_transient(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, urllib.error.URLError(socket.gaierror("dns down")))
        result = plan_with_ai("Hello", [], AIConfig(), api_key=TEST_KEY)
        assert result.ok is True
        assert "Offline plan" in result.explanation
        assert any("ai-error:PROVIDER_OFFLINE" in w for w in result.warnings)

    def test_no_fallback_for_auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, _http_error(401, json.dumps({"error": {"message": "Invalid API key"}}).encode()))
        result = plan_with_ai("Hello", [], AIConfig(), api_key=TEST_KEY)
        assert result.ok is False
        assert "AUTH_FAILED" in result.error
        assert "Offline plan" not in (result.explanation or "")

    def test_no_fallback_for_endpoint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, _http_error(404))
        result = plan_with_ai("Hello", [], AIConfig(), api_key=TEST_KEY)
        assert result.ok is False
        assert "ENDPOINT_NOT_FOUND" in result.error

    def test_fallback_set_matches_policy(self) -> None:
        assert "PROVIDER_OFFLINE" in OFFLINE_FALLBACK_ERRORS
        assert "TIMEOUT" in OFFLINE_FALLBACK_ERRORS
        assert "AUTH_FAILED" not in OFFLINE_FALLBACK_ERRORS
        assert "ENDPOINT_NOT_FOUND" not in OFFLINE_FALLBACK_ERRORS

    def test_offline_deterministic(self) -> None:
        first = plan_offline("find clinics")
        second = plan_offline("find clinics")
        assert first == second


class TestProviderToolNames:
    def test_wire_names_match_provider_pattern(self) -> None:
        import re

        from lunar_gis.ui.controller import build_registry

        pattern = re.compile(r"^[a-zA-Z0-9_-]+$")
        for schema in registry_tool_schemas(build_registry()):
            wire = to_provider_name(schema["name"])
            assert pattern.match(wire), wire

    def test_round_trip_all_registered(self) -> None:
        from lunar_gis.ui.controller import build_registry

        names = [s["name"] for s in registry_tool_schemas(build_registry())]
        assert len(names) == 19
        for name in names:
            assert from_provider_name(to_provider_name(name), names) == name

    def test_known_tricky_names(self) -> None:
        assert to_provider_name("data.describe_project") == "data_describe_project"
        assert to_provider_name("analysis.ahp_sensitivity") == "analysis_ahp_sensitivity"
        names = ["data.describe_project", "analysis.ahp_sensitivity"]
        assert from_provider_name("data_describe_project", names) == "data.describe_project"
        assert from_provider_name("analysis_ahp_sensitivity", names) == "analysis.ahp_sensitivity"
        assert from_provider_name("nope_missing", names) is None

    def test_rejects_undotted(self) -> None:
        with pytest.raises(ValueError):
            to_provider_name("nodots")

    def test_collision_fails_closed(self) -> None:
        with pytest.raises(ValueError):
            build_provider_tools(
                [
                    {"name": "a.b_c", "description": "", "input_schema": {"type": "object"}},
                    {"name": "a_b.c", "description": "", "input_schema": {"type": "object"}},
                ]
            )

    def test_parse_maps_back(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "content": "Checking.",
                        "tool_calls": [{"function": {"name": "data_describe_project", "arguments": "{}"}}],
                    }
                }
            ]
        }
        ok, parsed = openrouter_module.parse_response(
            payload, name_map={"data_describe_project": "data.describe_project"}
        )
        assert ok is True
        assert parsed["tool_calls"][0]["tool_name"] == "data.describe_project"

    def test_parse_rejects_unmapped(self) -> None:
        payload = {"choices": [{"message": {"tool_calls": [{"function": {"name": "evil_run", "arguments": "{}"}}]}}]}
        ok, parsed = openrouter_module.parse_response(payload, name_map={})
        assert ok is False
        assert parsed["error"] == "MALFORMED_TOOL_CALL"

    def test_planner_sends_wire_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from lunar_gis.ui.controller import build_registry

        captured: dict = {}

        def fake_chat(messages, config, api_key=None, tools=None):
            captured["tools"] = tools
            return True, {"choices": [{"message": {"content": "Done.", "tool_calls": []}}]}

        monkeypatch.setattr(openrouter_module, "chat_completion", fake_chat)
        result = plan_with_ai(
            "hello",
            [],
            AIConfig(),
            api_key="k",
            tool_schemas=registry_tool_schemas(build_registry()),
        )
        assert result.ok is True
        sent = {t["function"]["name"] for t in captured["tools"]}
        assert "data_describe_project" in sent
        assert not any("." in name for name in sent)

    def test_planner_maps_calls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from lunar_gis.ui.controller import build_registry

        def fake_chat(messages, config, api_key=None, tools=None):
            _ = (messages, config, api_key, tools)
            return True, {
                "choices": [
                    {
                        "message": {
                            "content": "Checking project.",
                            "tool_calls": [{"function": {"name": "data_describe_project", "arguments": "{}"}}],
                        }
                    }
                ],
            }

        monkeypatch.setattr(openrouter_module, "chat_completion", fake_chat)
        result = plan_with_ai(
            "hello",
            [],
            AIConfig(),
            api_key="k",
            tool_schemas=registry_tool_schemas(build_registry()),
        )
        assert result.ok is True
        assert result.tool_calls[0].tool_name == "data.describe_project"


class TestTextCallExtraction:
    NAMES = ["data.search_catalog", "data.describe_project"]

    def test_strict_fenced_shape(self) -> None:
        from lunar_gis.ai.toolcalling import extract_text_calls

        text = 'Searching now:\n```json {"tool": "data.search_catalog", "arguments": {"provider_id": "x"}} ```'
        calls = extract_text_calls(text, self.NAMES)
        assert len(calls) == 1
        assert calls[0]["tool_name"] == "data.search_catalog"
        assert calls[0]["arguments"] == {"provider_id": "x"}

    def test_wire_name_mapped(self) -> None:
        from lunar_gis.ai.toolcalling import extract_text_calls

        text = '```json {"tool_name": "data_search_catalog", "arguments": {}} ```'
        calls = extract_text_calls(text, self.NAMES)
        assert calls[0]["tool_name"] == "data.search_catalog"

    def test_functions_prefix_stripped(self) -> None:
        from lunar_gis.ai.toolcalling import extract_text_calls

        text = '```json {"tool": "functions.data_search_catalog", "arguments": {}} ```'
        calls = extract_text_calls(text, self.NAMES)
        assert calls[0]["tool_name"] == "data.search_catalog"

    def test_unmapped_dropped(self) -> None:
        from lunar_gis.ai.toolcalling import extract_text_calls

        text = '```json {"tool": "evil.run", "arguments": {}} ```'
        assert extract_text_calls(text, self.NAMES) == []

    def test_pseudo_code_ignored(self) -> None:
        from lunar_gis.ai.toolcalling import extract_text_calls

        text = '```json\ndata.search_catalog({\n  provider_id: "stac",\n})\n```'
        assert extract_text_calls(text, self.NAMES) == []
        assert extract_text_calls("no fences here", self.NAMES) == []

    def test_planner_merges_text_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from lunar_gis.ui.controller import build_registry

        def fake_chat(messages, config, api_key=None, tools=None):
            _ = (messages, config, api_key, tools)
            return True, {
                "choices": [
                    {
                        "message": {
                            "content": (
                                'Running:\n```json {"tool": "analysis.ahp", "arguments": '
                                '{"criteria": ["a", "b"], "matrix": [[1, 2], [0.5, 1]]}} ```'
                            ),
                            "tool_calls": [],
                        }
                    }
                ],
            }

        monkeypatch.setattr(openrouter_module, "chat_completion", fake_chat)
        result = plan_with_ai(
            "weight it",
            [],
            AIConfig(),
            api_key="k",
            tool_schemas=registry_tool_schemas(build_registry()),
        )
        assert result.ok is True
        assert result.tool_calls[0].tool_name == "analysis.ahp"

    def test_loop_executes_text_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from lunar_gis.ui.controller import build_registry, plan_request

        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        def fake_chat(messages, config, api_key=None, tools=None):
            _ = (messages, config, api_key, tools)
            return True, {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '```json {"tool": "analysis.ahp", "arguments": '
                                '{"criteria": ["a", "b"], "matrix": [[1, 2], [0.5, 1]]}} ```'
                            ),
                            "tool_calls": [],
                        }
                    }
                ],
            }

        monkeypatch.setattr(openrouter_module, "chat_completion", fake_chat)
        plan = plan_request("weight it", build_registry(), max_rounds=1)
        assert plan["ok"] is True
        assert [e["tool_name"] for e in plan["executed"]] == ["analysis.ahp"]


class TestBadRequest:
    def test_400_is_invalid_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, _http_error(400, b'{"error":{"message":"bad tools"}}'))
        ok, payload = openrouter_module.chat_completion(
            [{"role": "user", "content": "hi"}], AIConfig(), api_key=TEST_KEY
        )
        assert ok is False
        assert payload["error"] == "INVALID_REQUEST"
        assert "bad tools" in payload["detail"]

    def test_no_fallback_for_400(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, _http_error(400, b"{}"))
        result = plan_with_ai("Hello", [], AIConfig(), api_key=TEST_KEY)
        assert result.ok is False
        assert "INVALID_REQUEST" in result.error
        assert "INVALID_REQUEST" not in OFFLINE_FALLBACK_ERRORS

    def test_key_never_in_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, _http_error(401, b"{}"))
        ok, payload = openrouter_module.chat_completion(
            [{"role": "user", "content": "hi"}], AIConfig(), api_key=TEST_KEY
        )
        assert ok is False
        assert TEST_KEY not in json.dumps(payload)

    def test_key_absent_from_plan_records(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, FakeResponse(200, _ok_body()))
        result = plan_with_ai("Hello", [], AIConfig(), api_key=TEST_KEY)
        assert TEST_KEY not in json.dumps(
            {"explanation": result.explanation, "warnings": list(result.warnings), "requirement": result.requirement}
        )

    def test_audit_records_key_free(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", TEST_KEY)
        from lunar_gis.agent.execution import ControlledExecutor
        from lunar_gis.agent.registry import ToolExecutionContext
        from lunar_gis.analysis.tools import register_ahp_tool
        from lunar_gis.agent.registry import ToolRegistry

        registry = ToolRegistry()
        register_ahp_tool(registry)
        executor = ControlledExecutor(registry)
        result = executor.execute(
            "analysis.ahp",
            {"criteria": ["a", "b"], "matrix": [[1, 2], [0.5, 1]]},
            ToolExecutionContext(session_id="s"),
        )
        assert result.success is True
        for record in executor._audit_sink.records():
            assert TEST_KEY not in json.dumps(record.to_dict())


class TestGovernanceIntact:
    def test_unknown_tool_rejected_end_to_end(self) -> None:
        from lunar_gis.ai.toolcalling import execute_validated_calls
        from lunar_gis.agent.execution import ControlledExecutor
        from lunar_gis.agent.registry import ToolExecutionContext, ToolRegistry
        from lunar_gis.analysis.tools import register_ahp_tool

        registry = ToolRegistry()
        register_ahp_tool(registry)
        results = execute_validated_calls(
            [{"tool_name": "evil.run", "tool_version": "1.0.0", "arguments": {}}],
            registry,
            ControlledExecutor(registry),
            ToolExecutionContext(session_id="s"),
        )
        assert results[0]["ok"] is False
        assert results[0]["error"] == "UNKNOWN_TOOL"

    def test_high_risk_requires_confirmation(self) -> None:
        from lunar_gis.ui.controller import build_registry, create_executor, default_context, run_tool

        registry = build_registry()
        result = run_tool(
            create_executor(registry),
            "data.download_dataset",
            {"provider_id": "osm.overpass", "dataset_id": "d", "asset_id": "a"},
            default_context(),
        )
        assert result["ok"] is False
        assert "confirmation" in (result["error"] or "").lower()

    def test_privacy_context_excludes_raw(self) -> None:
        from lunar_gis.ai.context import project_summary_segment

        payload = {
            "snapshot_id": "s",
            "taken_at": "t",
            "records": [
                {
                    "name": "parcels",
                    "geometry_type": "2",
                    "crs_authid": "EPSG:4326",
                    "feature_count": 3,
                    "fields": [{"name": "owner"}, {"name": "value"}],
                    "storage": "file",
                    "valid": True,
                    "attributes": [{"owner": "Jane Doe", "value": 999}],
                }
            ],
        }
        text = project_summary_segment(payload).text
        assert "Jane Doe" not in text
        assert "999" not in text
        assert "owner" in text  # schema (field names) is allowed
