import json

import pytest

from lunar_gis.agent.registry import (
    ToolExecutionContext,
    ToolInput,
    ToolOutput,
    ToolRegistry,
    ToolResult,
    ToolRisk,
    ToolSpec,
    ToolVersion,
    validate_input_schema,
    validate_output_schema,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def noop() -> None:
    return None


def _spec(name: str = "test.tool", version: tuple[int, int, int] = (1, 0, 0), risk: str = "read") -> ToolSpec:
    return ToolSpec(name=name, version=ToolVersion(*version), risk=ToolRisk(risk))


# ===========================================================================
# ToolRisk
# ===========================================================================


@pytest.mark.unit
class TestToolRisk:
    def test_valid_values(self) -> None:
        assert ToolRisk.READ.value == "read"
        assert ToolRisk.LOW.value == "low"
        assert ToolRisk.MEDIUM.value == "medium"
        assert ToolRisk.HIGH.value == "high"

    def test_all_four_present(self) -> None:
        assert len(ToolRisk) == 4

    def test_invalid_value_rejected(self) -> None:
        with pytest.raises(ValueError):
            ToolRisk("danger")  # type: ignore[arg-type]

    def test_enum_member_access(self) -> None:
        assert ToolRisk("read") is ToolRisk.READ
        assert ToolRisk("high") is ToolRisk.HIGH


# ===========================================================================
# ToolVersion
# ===========================================================================


@pytest.mark.unit
class TestToolVersion:
    def test_valid_construction(self) -> None:
        v = ToolVersion(major=1, minor=2, patch=3)
        assert v.major == 1
        assert v.minor == 2
        assert v.patch == 3

    def test_default_values(self) -> None:
        v = ToolVersion()
        assert v.to_tuple() == (0, 0, 1)

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            ToolVersion(major=-1)

    def test_non_int_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            ToolVersion(major="1")  # type: ignore[arg-type]

    def test_ordering(self) -> None:
        assert ToolVersion(1, 0, 0) < ToolVersion(2, 0, 0)
        assert ToolVersion(1, 0, 0) < ToolVersion(1, 1, 0)
        assert ToolVersion(1, 0, 0) < ToolVersion(1, 0, 1)
        assert ToolVersion(1, 0, 0) == ToolVersion(1, 0, 0)

    def test_to_tuple(self) -> None:
        assert ToolVersion(2, 3, 4).to_tuple() == (2, 3, 4)

    def test_to_str(self) -> None:
        assert ToolVersion(2, 3, 4).to_str() == "2.3.4"

    def test_from_str(self) -> None:
        v = ToolVersion.from_str("1.2.3")
        assert v == ToolVersion(1, 2, 3)

    def test_from_str_invalid_format(self) -> None:
        with pytest.raises(ValueError, match="major.minor.patch"):
            ToolVersion.from_str("1.2")

    def test_from_str_non_int(self) -> None:
        with pytest.raises(ValueError, match="integers"):
            ToolVersion.from_str("1.2.x")

    def test_to_dict(self) -> None:
        assert ToolVersion(1, 2, 3).to_dict() == {"major": 1, "minor": 2, "patch": 3}

    def test_frozen(self) -> None:
        v = ToolVersion(1, 0, 0)
        with pytest.raises(AttributeError):
            v.major = 2  # type: ignore[misc]


# ===========================================================================
# ToolInput
# ===========================================================================


@pytest.mark.unit
class TestToolInput:
    def test_valid_input(self) -> None:
        inp = ToolInput(data={"key": "value", "count": 42})
        assert inp.data == {"key": "value", "count": 42}

    def test_empty_data(self) -> None:
        inp = ToolInput(data={})
        assert inp.data == {}

    def test_non_dict_rejected(self) -> None:
        with pytest.raises(TypeError, match="dict"):
            ToolInput(data=[1, 2, 3])  # type: ignore[arg-type]

    def test_json_serializable(self) -> None:
        inp = ToolInput(data={"a": "b", "c": 1, "d": 1.5, "e": True, "f": None})
        serialized = json.dumps(inp.to_dict())
        assert isinstance(serialized, str)

    def test_non_json_value_rejected(self) -> None:
        with pytest.raises(ValueError, match="JSON-compatible"):
            ToolInput(data={"bad": object()})

    def test_schema_validation_passes(self) -> None:
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}, "count": {"type": "integer"}},
            "required": ["name"],
            "additionalProperties": False,
        }
        inp = ToolInput(data={"name": "test", "count": 5}, schema=schema)
        assert inp.data["name"] == "test"

    def test_schema_rejects_missing_required(self) -> None:
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        with pytest.raises(ValueError, match="required field missing"):
            ToolInput(data={}, schema=schema)

    def test_schema_rejects_additional_properties(self) -> None:
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "additionalProperties": False,
        }
        with pytest.raises(ValueError, match="unexpected field"):
            ToolInput(data={"name": "test", "extra": True}, schema=schema)

    def test_schema_rejects_wrong_type(self) -> None:
        schema = {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
        }
        with pytest.raises(ValueError, match="expected integer"):
            ToolInput(data={"count": "not_int"}, schema=schema)

    def test_invalid_schema_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid input schema"):
            ToolInput(data={}, schema={"type": "string"})  # top-level must be object

    def test_schema_with_array_items(self) -> None:
        schema = {
            "type": "object",
            "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
        }
        inp = ToolInput(data={"tags": ["a", "b"]}, schema=schema)
        assert inp.data["tags"] == ["a", "b"]

    def test_schema_array_wrong_item_type(self) -> None:
        schema = {
            "type": "object",
            "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
        }
        with pytest.raises(ValueError, match="expected string"):
            ToolInput(data={"tags": [1, 2]}, schema=schema)

    def test_to_dict(self) -> None:
        inp = ToolInput(data={"a": 1}, schema={"type": "object"})
        d = inp.to_dict()
        assert d["data"] == {"a": 1}
        assert d["schema"] == {"type": "object"}

    def test_frozen(self) -> None:
        inp = ToolInput(data={"a": 1})
        with pytest.raises(AttributeError):
            inp.data = {}  # type: ignore[misc]


# ===========================================================================
# ToolOutput
# ===========================================================================


@pytest.mark.unit
class TestToolOutput:
    def test_valid_output(self) -> None:
        out = ToolOutput(data={"result": "success", "count": 3})
        assert out.data["result"] == "success"

    def test_non_dict_rejected(self) -> None:
        with pytest.raises(TypeError, match="dict"):
            ToolOutput(data="string")  # type: ignore[arg-type]

    def test_non_json_value_rejected(self) -> None:
        with pytest.raises(ValueError, match="JSON-compatible"):
            ToolOutput(data={"bad": set()})  # type: ignore[dict-item]

    def test_json_serializable(self) -> None:
        out = ToolOutput(data={"a": 1, "b": [2, 3], "c": {"d": 4}})
        serialized = json.dumps(out.to_dict())
        assert isinstance(serialized, str)

    def test_schema_validation(self) -> None:
        schema = {
            "type": "object",
            "properties": {"status": {"type": "string"}},
        }
        out = ToolOutput(data={"status": "ok"}, schema=schema)
        assert out.data["status"] == "ok"

    def test_invalid_output_schema_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid output schema"):
            ToolOutput(data={}, schema={"type": "array", "properties": "bad"})  # properties must be dict

    def test_to_dict(self) -> None:
        out = ToolOutput(data={"x": 1})
        d = out.to_dict()
        assert d["data"] == {"x": 1}

    def test_frozen(self) -> None:
        out = ToolOutput(data={"a": 1})
        with pytest.raises(AttributeError):
            out.data = {}  # type: ignore[misc]

    def test_empty_data(self) -> None:
        out = ToolOutput(data={})
        assert out.data == {}


# ===========================================================================
# ToolExecutionContext
# ===========================================================================


@pytest.mark.unit
class TestToolExecutionContext:
    def test_safe_construction(self) -> None:
        ctx = ToolExecutionContext(project_path="/tmp/project.qgz", qgis_version="4.0.1")
        assert ctx.project_path == "/tmp/project.qgz"
        assert ctx.qgis_version == "4.0.1"

    def test_defaults_are_none(self) -> None:
        ctx = ToolExecutionContext()
        assert ctx.project_path is None
        assert ctx.qgis_version is None
        assert ctx.session_id is None

    def test_no_secrets_field(self) -> None:
        ctx = ToolExecutionContext()
        d = ctx.to_dict()
        assert "api_key" not in d
        assert "token" not in d
        assert "secret" not in d
        assert "password" not in d
        assert "credential" not in d

    def test_no_executable_context(self) -> None:
        ctx = ToolExecutionContext()
        d = ctx.to_dict()
        for key in d:
            assert "exec" not in key.lower()
            assert "eval" not in key.lower()
            assert "code" not in key.lower()

    def test_to_dict(self) -> None:
        ctx = ToolExecutionContext(session_id="abc")
        d = ctx.to_dict()
        assert d == {"project_path": None, "qgis_version": None, "session_id": "abc"}

    def test_frozen(self) -> None:
        ctx = ToolExecutionContext()
        with pytest.raises(AttributeError):
            ctx.project_path = "/tmp"  # type: ignore[misc]


# ===========================================================================
# ToolResult
# ===========================================================================


@pytest.mark.unit
class TestToolResult:
    def test_success_result(self) -> None:
        out = ToolOutput(data={"value": 42})
        result = ToolResult(success=True, output=out)
        assert result.success is True
        assert result.output is not None
        assert result.error is None

    def test_failure_result(self) -> None:
        result = ToolResult(success=False, error="something went wrong")
        assert result.success is False
        assert result.error == "something went wrong"
        assert result.output is None

    def test_failure_requires_error(self) -> None:
        with pytest.raises(ValueError, match="must include an error"):
            ToolResult(success=False)

    def test_success_must_not_have_error(self) -> None:
        with pytest.raises(ValueError, match="must not include an error"):
            ToolResult(success=True, error="bad")

    def test_to_dict_success(self) -> None:
        out = ToolOutput(data={"ok": True})
        result = ToolResult(
            success=True,
            output=out,
            tool_name="test.tool",
            tool_version=ToolVersion(1, 0, 0),
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["output"]["data"] == {"ok": True}
        assert d["tool_name"] == "test.tool"
        assert d["tool_version"] == {"major": 1, "minor": 0, "patch": 0}

    def test_to_dict_failure(self) -> None:
        result = ToolResult(success=False, error="fail")
        d = result.to_dict()
        assert d["success"] is False
        assert d["error"] == "fail"
        assert "output" not in d

    def test_json_serializable(self) -> None:
        result = ToolResult(
            success=True,
            output=ToolOutput(data={"nested": {"a": [1, 2, 3]}}),
            tool_name="x.y",
        )
        serialized = json.dumps(result.to_dict())
        assert isinstance(serialized, str)

    def test_frozen(self) -> None:
        result = ToolResult(success=True)
        with pytest.raises(AttributeError):
            result.success = False  # type: ignore[misc]


# ===========================================================================
# ToolSpec
# ===========================================================================


@pytest.mark.unit
class TestToolSpec:
    def test_valid_spec(self) -> None:
        spec = _spec("project.list_layers", (1, 0, 0), "read")
        assert spec.name == "project.list_layers"
        assert spec.version == ToolVersion(1, 0, 0)
        assert spec.risk == ToolRisk.READ

    def test_with_handler(self) -> None:
        spec = ToolSpec(
            name="x.y",
            version=ToolVersion(1, 0, 0),
            risk=ToolRisk.LOW,
            handler=noop,
        )
        assert spec.handler is noop

    def test_handler_defaults_none(self) -> None:
        spec = _spec()
        assert spec.handler is None

    def test_name_must_be_nonempty(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            ToolSpec(name="", version=ToolVersion(), risk=ToolRisk.READ)

    def test_name_must_have_dot(self) -> None:
        with pytest.raises(ValueError, match="dot notation"):
            ToolSpec(name="nodot", version=ToolVersion(), risk=ToolRisk.READ)

    def test_version_must_be_toolversion(self) -> None:
        with pytest.raises(TypeError, match="ToolVersion"):
            ToolSpec(name="a.b", version=1, risk=ToolRisk.READ)  # type: ignore[arg-type]

    def test_risk_must_be_toolrisk(self) -> None:
        with pytest.raises(TypeError, match="ToolRisk"):
            ToolSpec(name="a.b", version=ToolVersion(), risk="read")  # type: ignore[arg-type]

    def test_invalid_input_schema_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid input_schema"):
            ToolSpec(
                name="a.b",
                version=ToolVersion(),
                risk=ToolRisk.READ,
                input_schema={"type": "string"},
            )

    def test_invalid_output_schema_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid output_schema"):
            ToolSpec(
                name="a.b",
                version=ToolVersion(),
                risk=ToolRisk.READ,
                output_schema={"type": "array", "properties": "bad"},
            )

    def test_to_dict(self) -> None:
        spec = _spec("test.tool", (2, 1, 0), "medium")
        d = spec.to_dict()
        assert d["name"] == "test.tool"
        assert d["version"] == {"major": 2, "minor": 1, "patch": 0}
        assert d["risk"] == "medium"
        assert "handler" not in d  # handler excluded from serialization

    def test_to_dict_with_schemas(self) -> None:
        spec = ToolSpec(
            name="a.b",
            version=ToolVersion(),
            risk=ToolRisk.READ,
            input_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
            output_schema={"type": "object", "properties": {"y": {"type": "string"}}},
        )
        d = spec.to_dict()
        assert "input_schema" in d
        assert "output_schema" in d

    def test_frozen(self) -> None:
        spec = _spec()
        with pytest.raises(AttributeError):
            spec.name = "other"  # type: ignore[misc]

    def test_description_optional(self) -> None:
        spec = ToolSpec(
            name="a.b",
            version=ToolVersion(),
            risk=ToolRisk.READ,
            description="A test tool",
        )
        assert spec.description == "A test tool"
        d = spec.to_dict()
        assert d["description"] == "A test tool"


# ===========================================================================
# ToolRegistry
# ===========================================================================


@pytest.mark.unit
class TestToolRegistry:
    def test_register_and_lookup(self) -> None:
        registry = ToolRegistry()
        registry.register(_spec("project.list_layers"))
        assert registry.names() == ("project.list_layers",)
        assert registry.get("project.list_layers").version == ToolVersion(1, 0, 0)

    def test_rejects_duplicate_tool(self) -> None:
        registry = ToolRegistry()
        spec = _spec("project.list_layers")
        registry.register(spec)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(_spec("project.list_layers", (2, 0, 0)))

    def test_rejects_non_spec(self) -> None:
        registry = ToolRegistry()
        with pytest.raises(TypeError, match="ToolSpec"):
            registry.register("not a spec")  # type: ignore[arg-type]

    def test_get_unknown_raises(self) -> None:
        registry = ToolRegistry()
        with pytest.raises(KeyError, match="Unknown tool"):
            registry.get("missing.tool")

    def test_has(self) -> None:
        registry = ToolRegistry()
        assert not registry.has("a.b")
        registry.register(_spec("a.b"))
        assert registry.has("a.b")

    def test_remove(self) -> None:
        registry = ToolRegistry()
        registry.register(_spec("a.b"))
        removed = registry.remove("a.b")
        assert removed.name == "a.b"
        assert not registry.has("a.b")

    def test_remove_unknown_raises(self) -> None:
        registry = ToolRegistry()
        with pytest.raises(KeyError, match="Unknown tool"):
            registry.remove("missing.tool")

    def test_names_sorted(self) -> None:
        registry = ToolRegistry()
        registry.register(_spec("b.tool"))
        registry.register(_spec("a.tool"))
        registry.register(_spec("c.tool", (1, 0, 0), "medium"))
        assert registry.names() == ("a.tool", "b.tool", "c.tool")

    def test_all_specs_sorted(self) -> None:
        registry = ToolRegistry()
        registry.register(_spec("b.tool"))
        registry.register(_spec("a.tool"))
        specs = registry.all_specs()
        assert [s.name for s in specs] == ["a.tool", "b.tool"]

    def test_allows_all_valid_risks(self) -> None:
        for risk in ("read", "low", "medium", "high"):
            r = ToolRegistry()
            r.register(_spec(f"t.{risk}", (1, 0, 0), risk))
            assert r.get(f"t.{risk}").risk == ToolRisk(risk)

    def test_stores_version_and_handler(self) -> None:
        def handler(x: object) -> object:
            return x

        spec = ToolSpec(
            name="x.y",
            version=ToolVersion(3, 0, 0),
            risk=ToolRisk.HIGH,
            handler=handler,
        )
        registry = ToolRegistry()
        registry.register(spec)
        got = registry.get("x.y")
        assert got.version == ToolVersion(3, 0, 0)
        assert got.handler is handler
        assert got.name == "x.y"

    def test_validate_spec_valid(self) -> None:
        registry = ToolRegistry()
        spec = _spec("a.b", (1, 0, 0), "low")
        errors = registry.validate_spec(spec)
        assert errors == []

    def test_validate_spec_invalid(self) -> None:
        registry = ToolRegistry()

        # ToolSpec constructor already rejects invalid specs, so test validate_spec
        # by constructing a mock-like object that bypasses __post_init__
        class FakeSpec:
            name = "a.b"
            version = ToolVersion()
            risk = ToolRisk.READ
            input_schema = {"type": "string"}  # invalid: must be object
            output_schema: dict = {}

        errors = registry.validate_spec(FakeSpec())  # type: ignore[arg-type]
        assert len(errors) > 0
        assert any("top-level" in e for e in errors)

    def test_to_dict(self) -> None:
        registry = ToolRegistry()
        registry.register(_spec("a.b"))
        d = registry.to_dict()
        assert "a.b" in d
        assert d["a.b"]["name"] == "a.b"

    def test_registry_does_not_execute_handlers(self) -> None:
        call_count = 0

        def counting_handler() -> None:
            nonlocal call_count
            call_count += 1

        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="a.b",
                version=ToolVersion(),
                risk=ToolRisk.READ,
                handler=counting_handler,
            )
        )
        registry.get("a.b")
        registry.names()
        registry.to_dict()
        assert call_count == 0

    def test_empty_registry(self) -> None:
        registry = ToolRegistry()
        assert registry.names() == ()
        assert registry.all_specs() == ()
        assert registry.to_dict() == {}


# ===========================================================================
# Schema validation
# ===========================================================================


@pytest.mark.unit
class TestSchemaValidation:
    def test_valid_input_schema(self) -> None:
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        errors = validate_input_schema(schema)
        assert errors == []

    def test_invalid_top_level_type(self) -> None:
        errors = validate_input_schema({"type": "string"})
        assert any("top-level" in e for e in errors)

    def test_missing_required_not_in_properties(self) -> None:
        schema = {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["b"],
        }
        errors = validate_input_schema(schema)
        assert any("unknown property" in e for e in errors)

    def test_valid_output_schema(self) -> None:
        schema = {
            "type": "object",
            "properties": {"result": {"type": "string"}},
        }
        errors = validate_output_schema(schema)
        assert errors == []

    def test_unsupported_type_in_property(self) -> None:
        schema = {
            "type": "object",
            "properties": {"x": {"type": "fnord"}},
        }
        errors = validate_input_schema(schema)
        assert any("unsupported type" in e for e in errors)


# ===========================================================================
# Security regression tests
# ===========================================================================


@pytest.mark.unit
class TestSecurityRegression:
    def test_no_exec_in_tool_input(self) -> None:
        with pytest.raises(ValueError, match="JSON-compatible"):
            ToolInput(data={"cmd": noop})  # functions are not JSON-serializable

    def test_no_eval_in_tool_input(self) -> None:
        with pytest.raises(ValueError, match="JSON-compatible"):
            ToolInput(data={"payload": lambda: None})  # lambdas are not JSON-serializable

    def test_no_executable_objects_in_input(self) -> None:
        with pytest.raises(ValueError, match="JSON-compatible"):
            ToolInput(data={"handler": noop})

    def test_no_executable_objects_in_output(self) -> None:
        with pytest.raises(ValueError, match="JSON-compatible"):
            ToolOutput(data={"handler": noop})

    def test_toolresult_no_arbitrary_objects(self) -> None:
        result = ToolResult(success=True, output=ToolOutput(data={"x": 1}))
        d = result.to_dict()
        serialized = json.dumps(d)
        assert "function" not in serialized
        assert "import" not in serialized

    def test_tool_spec_handler_not_in_serialization(self) -> None:
        spec = ToolSpec(
            name="a.b",
            version=ToolVersion(),
            risk=ToolRisk.READ,
            handler=noop,
        )
        d = spec.to_dict()
        assert "handler" not in d

    def test_tool_registry_no_exec_method(self) -> None:
        registry = ToolRegistry()
        assert not hasattr(registry, "execute")
        assert not hasattr(registry, "run")
        assert not hasattr(registry, "invoke")
        assert not hasattr(registry, "call")

    def test_tool_execution_context_no_secrets(self) -> None:
        ctx = ToolExecutionContext()
        d = ctx.to_dict()
        for key in d:
            assert key not in ("api_key", "token", "secret", "password", "credential", "env")

    def test_non_string_dict_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="dict keys must be strings"):
            ToolInput(data={1: "value"})  # type: ignore[dict-item]

    def test_nested_non_json_in_list_rejected(self) -> None:
        with pytest.raises(ValueError, match="JSON-compatible"):
            ToolInput(data={"items": [object()]})

    def test_nested_executable_object_rejected(self) -> None:
        with pytest.raises(ValueError, match="JSON-compatible"):
            ToolInput(data={"cmd": {"fn": noop}})
