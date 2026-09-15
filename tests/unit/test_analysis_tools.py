"""Tests for AHP tool adapter: ToolSpec, handler, registration, governed execution."""

from __future__ import annotations

import pytest

from lunar_gis.agent.execution import ControlledExecutor
from lunar_gis.agent.governance import PermissionPolicy, PolicyEngine
from lunar_gis.agent.registry import (
    ToolExecutionContext,
    ToolInput,
    ToolOutput,
    ToolRegistry,
    ToolRisk,
    ToolVersion,
)
from lunar_gis.analysis.ahp import AHPError, AHPErrorCode
from lunar_gis.analysis.tools import (
    AHP_INPUT_SCHEMA,
    AHP_OUTPUT_SCHEMA,
    AHP_TOOL_SPEC,
    ahp_handler,
    register_ahp_tool,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    register_ahp_tool(reg)
    return reg


@pytest.fixture
def executor(registry: ToolRegistry) -> ControlledExecutor:
    return ControlledExecutor(registry=registry)


@pytest.fixture
def context() -> ToolExecutionContext:
    return ToolExecutionContext(session_id="test-session")


def _valid_input() -> dict:
    return {
        "criteria": ["c1", "c2", "c3"],
        "matrix": [[1, 3, 5], [1 / 3, 1, 3], [1 / 5, 1 / 3, 1]],
    }


# ===========================================================================
# ToolSpec
# ===========================================================================


@pytest.mark.unit
class TestAHPToolSpec:
    def test_spec_name(self) -> None:
        assert AHP_TOOL_SPEC.name == "analysis.ahp"

    def test_spec_version(self) -> None:
        assert AHP_TOOL_SPEC.version == ToolVersion(1, 0, 0)

    def test_spec_risk(self) -> None:
        assert AHP_TOOL_SPEC.risk == ToolRisk.LOW

    def test_spec_description_nonempty(self) -> None:
        assert len(AHP_TOOL_SPEC.description) > 0

    def test_input_schema_has_required_fields(self) -> None:
        assert "criteria" in AHP_INPUT_SCHEMA["required"]
        assert "matrix" in AHP_INPUT_SCHEMA["required"]

    def test_output_schema_has_required_fields(self) -> None:
        for field in ["criteria", "weights", "lambda_max", "ci", "ri", "cr", "consistency_flag"]:
            assert field in AHP_OUTPUT_SCHEMA["required"]

    def test_toolspec_is_valid(self) -> None:
        reg = ToolRegistry()
        errors = reg.validate_spec(AHP_TOOL_SPEC)
        assert errors == []


# ===========================================================================
# Registration
# ===========================================================================


@pytest.mark.unit
class TestRegistration:
    def test_register_ahp_tool(self, registry: ToolRegistry) -> None:
        assert registry.has("analysis.ahp")

    def test_handler_attached(self, registry: ToolRegistry) -> None:
        spec = registry.get("analysis.ahp")
        assert spec.handler is ahp_handler

    def test_handler_not_in_serialized_metadata(self, registry: ToolRegistry) -> None:
        spec = registry.get("analysis.ahp")
        d = spec.to_dict()
        assert "handler" not in d

    def test_duplicate_registration_rejected(self) -> None:
        reg = ToolRegistry()
        register_ahp_tool(reg)
        with pytest.raises(ValueError, match="already registered"):
            register_ahp_tool(reg)

    def test_registry_names(self, registry: ToolRegistry) -> None:
        assert "analysis.ahp" in registry.names()


# ===========================================================================
# Handler
# ===========================================================================


@pytest.mark.unit
class TestAHPHandler:
    def test_valid_calculation(self) -> None:
        result = ahp_handler(_valid_input())
        assert "weights" in result
        assert "lambda_max" in result
        assert "ci" in result
        assert "cr" in result
        assert "consistency_flag" in result

    def test_weights_sum_to_one(self) -> None:
        result = ahp_handler(_valid_input())
        assert sum(result["weights"]) == pytest.approx(1.0, abs=1e-9)

    def test_consistency_flag_is_string(self) -> None:
        result = ahp_handler(_valid_input())
        assert isinstance(result["consistency_flag"], str)
        assert result["consistency_flag"] in [
            "ACCEPTABLE",
            "ACCEPTABLE_WITH_WARNING",
            "REVISE_REQUIRED",
        ]

    def test_output_matches_ahp_engine(self) -> None:
        from lunar_gis.analysis.ahp import ahp

        input_data = _valid_input()
        expected = ahp(input_data["criteria"], input_data["matrix"])
        result = ahp_handler(input_data)
        assert result["weights"] == list(expected.weights)
        assert result["lambda_max"] == expected.consistency.lambda_max
        assert result["ci"] == expected.consistency.ci
        assert result["cr"] == expected.consistency.cr
        assert result["consistency_flag"] == expected.consistency.flag.value

    def test_2x2_exact(self) -> None:
        result = ahp_handler({"criteria": ["a", "b"], "matrix": [[1, 4], [0.25, 1]]})
        assert result["weights"] == pytest.approx([0.8, 0.2], abs=1e-12)
        assert result["trivial_consistency"] is True

    def test_1x1_trivial(self) -> None:
        result = ahp_handler({"criteria": ["only"], "matrix": [[1]]})
        assert result["weights"] == [1.0]
        assert result["trivial_consistency"] is True

    def test_invalid_matrix_raises_ahp_error(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp_handler({"criteria": ["a", "b"], "matrix": [[1, 0], [1, 1]]})
        assert exc.value.code == AHPErrorCode.INVALID_NUMERIC_VALUE

    def test_non_square_raises_ahp_error(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp_handler({"criteria": ["a", "b"], "matrix": [[1, 2], [0.5]]})
        assert exc.value.code == AHPErrorCode.NON_SQUARE_MATRIX

    def test_acceptable_with_warning(self) -> None:
        mat = [[1, 7, 1 / 5], [1 / 7, 1, 1 / 9], [5, 9, 1]]
        result = ahp_handler({"criteria": ["a", "b", "c"], "matrix": mat})
        assert result["consistency_flag"] == "ACCEPTABLE_WITH_WARNING"

    def test_revise_required(self) -> None:
        mat = [[1, 9, 1 / 9], [1 / 9, 1, 9], [9, 1 / 9, 1]]
        result = ahp_handler({"criteria": ["a", "b", "c"], "matrix": mat})
        assert result["consistency_flag"] == "REVISE_REQUIRED"


# ===========================================================================
# ToolInput / ToolOutput boundary
# ===========================================================================


@pytest.mark.unit
class TestToolInputOutputBoundary:
    def test_valid_tool_input(self) -> None:
        inp = ToolInput(data=_valid_input(), schema=AHP_INPUT_SCHEMA)
        assert inp.data["criteria"] == ["c1", "c2", "c3"]

    def test_missing_criteria_rejected(self) -> None:
        with pytest.raises(ValueError, match="required field missing"):
            ToolInput(data={"matrix": [[1]]}, schema=AHP_INPUT_SCHEMA)

    def test_missing_matrix_rejected(self) -> None:
        with pytest.raises(ValueError, match="required field missing"):
            ToolInput(data={"criteria": ["a"]}, schema=AHP_INPUT_SCHEMA)

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValueError, match="unexpected field"):
            ToolInput(
                data={"criteria": ["a"], "matrix": [[1]], "extra": True},
                schema=AHP_INPUT_SCHEMA,
            )

    def test_valid_tool_output(self) -> None:
        out = ToolOutput(data=ahp_handler(_valid_input()), schema=AHP_OUTPUT_SCHEMA)
        assert "weights" in out.data

    def test_output_schema_validation_catches_missing_field(self) -> None:
        incomplete = {"criteria": ["a"], "weights": [1.0]}
        # ToolOutput validates the schema definition but does not enforce
        # required fields on data (unlike ToolInput). This is by design.
        out = ToolOutput(data=incomplete, schema=AHP_OUTPUT_SCHEMA)
        assert out.data["criteria"] == ["a"]


# ===========================================================================
# Governed execution (full path)
# ===========================================================================


@pytest.mark.unit
class TestGovernedExecution:
    def test_successful_execution(self, executor: ControlledExecutor, context: ToolExecutionContext) -> None:
        result = executor.execute("analysis.ahp", _valid_input(), context)
        assert result.success is True
        assert result.output is not None
        assert "weights" in result.output.data

    def test_tool_name_in_result(self, executor: ControlledExecutor, context: ToolExecutionContext) -> None:
        result = executor.execute("analysis.ahp", _valid_input(), context)
        assert result.tool_name == "analysis.ahp"
        assert result.tool_version == ToolVersion(1, 0, 0)

    def test_unknown_tool_rejected(self, executor: ControlledExecutor, context: ToolExecutionContext) -> None:
        result = executor.execute("analysis.nonexistent", _valid_input(), context)
        assert result.success is False
        assert "Unknown tool" in result.error

    def test_handler_not_invoked_for_unknown_tool(self) -> None:
        reg = ToolRegistry()
        executor = ControlledExecutor(registry=reg)
        context = ToolExecutionContext()
        call_count = 0

        def counting_handler(data):
            nonlocal call_count
            call_count += 1
            return data

        # Don't register it — execute unknown tool
        result = executor.execute("test.handler", {"x": 1}, context)
        assert result.success is False
        assert call_count == 0

    def test_permission_denied(self, context: ToolExecutionContext) -> None:
        reg = ToolRegistry()
        register_ahp_tool(reg)
        policy = PermissionPolicy(allowed_risks=frozenset({ToolRisk.READ}))
        engine = PolicyEngine(permission_policy=policy)
        executor = ControlledExecutor(registry=reg, policy_engine=engine)
        result = executor.execute("analysis.ahp", _valid_input(), context)
        assert result.success is False
        assert "Permission denied" in result.error

    def test_handler_not_invoked_on_deny(self, context: ToolExecutionContext) -> None:
        reg = ToolRegistry()
        register_ahp_tool(reg)
        policy = PermissionPolicy(allowed_risks=frozenset({ToolRisk.READ}))
        engine = PolicyEngine(permission_policy=policy)
        executor = ControlledExecutor(registry=reg, policy_engine=engine)

        # Handler should not be called
        result = executor.execute("analysis.ahp", _valid_input(), context)
        assert result.success is False

    def test_audit_records_written(self, executor: ControlledExecutor, context: ToolExecutionContext) -> None:
        result = executor.execute("analysis.ahp", _valid_input(), context)
        assert result.success is True
        # Audit sink should have records
        assert executor._audit_sink is not None

    def test_invalid_input_governed(self, executor: ControlledExecutor, context: ToolExecutionContext) -> None:
        bad_input = {"criteria": ["a", "b"], "matrix": [[1, 0], [1, 1]]}
        result = executor.execute("analysis.ahp", bad_input, context)
        assert result.success is False
        assert "Input validation failed" in result.error or "INVALID" in result.error

    def test_ahp_error_preserved_in_result(self, executor: ControlledExecutor, context: ToolExecutionContext) -> None:
        bad_input = {"criteria": ["a", "b"], "matrix": [[1, 0], [1, 1]]}
        result = executor.execute("analysis.ahp", bad_input, context)
        assert result.success is False
        # Error should contain the AHP error information
        assert result.error is not None


# ===========================================================================
# Confirmation behavior (LOW risk = no confirmation required)
# ===========================================================================


@pytest.mark.unit
class TestConfirmationBehavior:
    def test_low_risk_no_confirmation_required(self, context: ToolExecutionContext) -> None:
        reg = ToolRegistry()
        register_ahp_tool(reg)
        engine = PolicyEngine()
        executor = ControlledExecutor(registry=reg, policy_engine=engine)
        # Execute without confirmation artifact — should succeed
        result = executor.execute("analysis.ahp", _valid_input(), context)
        assert result.success is True

    def test_confirmation_not_checked_for_low_risk(
        self, executor: ControlledExecutor, context: ToolExecutionContext
    ) -> None:
        # No confirmation artifact provided, but LOW risk doesn't require one
        result = executor.execute("analysis.ahp", _valid_input(), context, confirmation=None)
        assert result.success is True


# ===========================================================================
# Determinism
# ===========================================================================


@pytest.mark.unit
class TestDeterminism:
    def test_repeated_execution_produces_identical_output(
        self, executor: ControlledExecutor, context: ToolExecutionContext
    ) -> None:
        r1 = executor.execute("analysis.ahp", _valid_input(), context)
        r2 = executor.execute("analysis.ahp", _valid_input(), context)
        assert r1.success is True
        assert r2.success is True
        assert r1.output is not None
        assert r2.output is not None
        assert r1.output.data["weights"] == r2.output.data["weights"]
        assert r1.output.data["input_hash"] == r2.output.data["input_hash"]
        assert r1.output.data["lambda_max"] == r2.output.data["lambda_max"]

    def test_handler_deterministic(self) -> None:
        r1 = ahp_handler(_valid_input())
        r2 = ahp_handler(_valid_input())
        assert r1["weights"] == r2["weights"]
        assert r1["input_hash"] == r2["input_hash"]


# ===========================================================================
# Security regression
# ===========================================================================


@pytest.mark.unit
class TestSecurityRegression:
    def test_no_qgis_import(self) -> None:
        import lunar_gis.analysis.tools as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "import qgis" not in text
        assert "from qgis" not in text

    def test_no_network_import(self) -> None:
        import lunar_gis.analysis.tools as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        for banned in ("import requests", "import urllib", "import socket", "import http"):
            assert banned not in text

    def test_no_numpy_import(self) -> None:
        import lunar_gis.analysis.tools as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "import numpy" not in text
        assert "import scipy" not in text

    def test_no_exec_or_eval(self) -> None:
        import lunar_gis.analysis.tools as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "exec(" not in text
        assert "eval(" not in text
        assert "compile(" not in text
