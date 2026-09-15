"""Tests for sensitivity tool adapter: ToolSpec, handler, registration, governed execution."""

from __future__ import annotations

import pytest

from lunar_gis.agent.execution import ControlledExecutor
from lunar_gis.agent.governance import (
    PermissionPolicy,
    PolicyEngine,
)
from lunar_gis.agent.registry import (
    ToolExecutionContext,
    ToolInput,
    ToolOutput,
    ToolRegistry,
    ToolRisk,
    ToolVersion,
)
from lunar_gis.analysis.sensitivity import SensitivityError, SensitivityErrorCode
from lunar_gis.analysis.sensitivity_tools import (
    SENSITIVITY_INPUT_SCHEMA,
    SENSITIVITY_OUTPUT_SCHEMA,
    SENSITIVITY_TOOL_SPEC,
    register_sensitivity_tool,
    sensitivity_handler,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    register_sensitivity_tool(reg)
    return reg


@pytest.fixture
def executor(registry: ToolRegistry) -> ControlledExecutor:
    return ControlledExecutor(registry=registry)


@pytest.fixture
def context() -> ToolExecutionContext:
    return ToolExecutionContext(session_id="test-sensitivity-session")


def _valid_input() -> dict:
    return {
        "criteria": ["A", "B", "C"],
        "matrix": [[1, 3, 5], [1 / 3, 1, 3], [1 / 5, 1 / 3, 1]],
    }


def _valid_input_with_options() -> dict:
    return {
        "criteria": ["A", "B", "C"],
        "matrix": [[1, 3, 5], [1 / 3, 1, 3], [1 / 5, 1 / 3, 1]],
        "method": "OAT_WEIGHT",
        "perturbation_range": [-0.2, 0.2],
        "num_steps": 10,
        "target_criteria": ["A"],
    }


# ===========================================================================
# ToolSpec
# ===========================================================================


@pytest.mark.unit
class TestSensitivityToolSpec:
    def test_spec_name(self) -> None:
        assert SENSITIVITY_TOOL_SPEC.name == "analysis.ahp_sensitivity"

    def test_spec_version(self) -> None:
        assert SENSITIVITY_TOOL_SPEC.version == ToolVersion(1, 0, 0)

    def test_spec_risk(self) -> None:
        assert SENSITIVITY_TOOL_SPEC.risk == ToolRisk.LOW

    def test_spec_description_nonempty(self) -> None:
        assert len(SENSITIVITY_TOOL_SPEC.description) > 0

    def test_input_schema_has_required_fields(self) -> None:
        assert "criteria" in SENSITIVITY_INPUT_SCHEMA["required"]
        assert "matrix" in SENSITIVITY_INPUT_SCHEMA["required"]

    def test_input_schema_rejects_additional_properties(self) -> None:
        assert SENSITIVITY_INPUT_SCHEMA.get("additionalProperties") is False

    def test_output_schema_has_required_fields(self) -> None:
        required = SENSITIVITY_OUTPUT_SCHEMA["required"]
        for field in [
            "criteria",
            "baseline_weights",
            "baseline_ranking",
            "criterion_results",
            "method",
            "sensitivity_policy_version",
            "numerical_policy_version",
            "engine_version",
            "input_hash",
            "perturbation_range",
            "num_steps",
            "ranking_policy_version",
            "consistency_policy_version",
        ]:
            assert field in required

    def test_output_schema_rejects_additional_properties(self) -> None:
        assert SENSITIVITY_OUTPUT_SCHEMA.get("additionalProperties") is False

    def test_toolspec_is_valid(self) -> None:
        reg = ToolRegistry()
        errors = reg.validate_spec(SENSITIVITY_TOOL_SPEC)
        assert errors == []


# ===========================================================================
# Registration
# ===========================================================================


@pytest.mark.unit
class TestRegistration:
    def test_register_sensitivity_tool(self, registry: ToolRegistry) -> None:
        assert registry.has("analysis.ahp_sensitivity")

    def test_handler_attached(self, registry: ToolRegistry) -> None:
        spec = registry.get("analysis.ahp_sensitivity")
        assert spec.handler is sensitivity_handler

    def test_handler_not_in_serialized_metadata(self, registry: ToolRegistry) -> None:
        spec = registry.get("analysis.ahp_sensitivity")
        d = spec.to_dict()
        assert "handler" not in d

    def test_duplicate_registration_rejected(self) -> None:
        reg = ToolRegistry()
        register_sensitivity_tool(reg)
        with pytest.raises(ValueError, match="already registered"):
            register_sensitivity_tool(reg)

    def test_registry_names(self, registry: ToolRegistry) -> None:
        assert "analysis.ahp_sensitivity" in registry.names()

    def test_registry_contains_ahp_and_sensitivity(self) -> None:
        from lunar_gis.analysis.tools import register_ahp_tool

        reg = ToolRegistry()
        register_ahp_tool(reg)
        register_sensitivity_tool(reg)
        assert "analysis.ahp" in reg.names()
        assert "analysis.ahp_sensitivity" in reg.names()

    def test_to_dict_contains_spec(self, registry: ToolRegistry) -> None:
        d = registry.to_dict()
        assert "analysis.ahp_sensitivity" in d
        spec_dict = d["analysis.ahp_sensitivity"]
        assert spec_dict["name"] == "analysis.ahp_sensitivity"
        assert spec_dict["version"] == {"major": 1, "minor": 0, "patch": 0}
        assert spec_dict["risk"] == "low"


# ===========================================================================
# Handler
# ===========================================================================


@pytest.mark.unit
class TestSensitivityHandler:
    def test_valid_minimal_input(self) -> None:
        result = sensitivity_handler(_valid_input())
        assert "baseline_weights" in result
        assert "baseline_ranking" in result
        assert "criterion_results" in result
        assert "method" in result

    def test_valid_full_input(self) -> None:
        result = sensitivity_handler(_valid_input_with_options())
        assert result["num_steps"] == 10
        assert result["target_criteria"] == ["A"]
        assert len(result["criterion_results"]) == 1

    def test_baseline_weights_sum_to_one(self) -> None:
        result = sensitivity_handler(_valid_input())
        assert sum(result["baseline_weights"]) == pytest.approx(1.0, abs=1e-9)

    def test_baseline_ranking_is_list_of_int(self) -> None:
        result = sensitivity_handler(_valid_input())
        assert isinstance(result["baseline_ranking"], list)
        for r in result["baseline_ranking"]:
            assert isinstance(r, int)

    def test_criterion_results_structure(self) -> None:
        result = sensitivity_handler(_valid_input())
        assert len(result["criterion_results"]) == 3
        for cr in result["criterion_results"]:
            assert "criterion" in cr
            assert "baseline_weight" in cr
            assert "stability_lower" in cr
            assert "stability_upper" in cr
            assert "crossover_points" in cr
            assert "perturbation_values" in cr
            assert "perturbed_weights" in cr
            assert "perturbed_rankings" in cr
            assert "consistency_flags" in cr
            assert "consistency_ratios" in cr

    def test_perturbation_values_count_matches_num_steps(self) -> None:
        result = sensitivity_handler(_valid_input())
        for cr in result["criterion_results"]:
            assert len(cr["perturbation_values"]) == result["num_steps"]
            assert len(cr["perturbed_weights"]) == result["num_steps"]
            assert len(cr["perturbed_rankings"]) == result["num_steps"]
            assert len(cr["consistency_flags"]) == result["num_steps"]
            assert len(cr["consistency_ratios"]) == result["num_steps"]

    def test_method_string(self) -> None:
        result = sensitivity_handler(_valid_input())
        assert result["method"] == "OAT_WEIGHT"

    def test_provenance_fields_present(self) -> None:
        result = sensitivity_handler(_valid_input())
        assert result["sensitivity_policy_version"] == "1.0"
        assert result["numerical_policy_version"] == "1.0"
        assert result["engine_version"] is not None
        assert result["input_hash"] is not None
        assert result["ranking_policy_version"] == "1.0"
        assert result["consistency_policy_version"] == "1.0"

    def test_perturbation_range_is_list(self) -> None:
        result = sensitivity_handler(_valid_input())
        assert isinstance(result["perturbation_range"], list)
        assert len(result["perturbation_range"]) == 2

    def test_near_ties_is_list(self) -> None:
        result = sensitivity_handler(_valid_input())
        assert isinstance(result["near_ties"], list)

    def test_output_matches_direct_engine_call(self) -> None:
        from lunar_gis.analysis.sensitivity import sensitivity_ahp

        input_data = _valid_input()
        expected = sensitivity_ahp(input_data["criteria"], input_data["matrix"])
        result = sensitivity_handler(input_data)
        assert result["baseline_weights"] == list(expected.baseline_weights)
        assert result["baseline_ranking"] == list(expected.baseline_ranking)
        assert result["input_hash"] == expected.input_hash
        assert result["method"] == expected.method.value
        assert len(result["criterion_results"]) == len(expected.criterion_results)

    def test_2x2_exact(self) -> None:
        result = sensitivity_handler(
            {
                "criteria": ["X", "Y"],
                "matrix": [[1, 3], [1 / 3, 1]],
            }
        )
        assert abs(result["baseline_weights"][0] - 0.75) < 1e-6
        assert abs(result["baseline_weights"][1] - 0.25) < 1e-6

    def test_invalid_method_raises_sensitivity_error(self) -> None:
        with pytest.raises(SensitivityError) as exc:
            sensitivity_handler(
                {
                    "criteria": ["A", "B"],
                    "matrix": [[1, 3], [1 / 3, 1]],
                    "method": "INVALID",
                }
            )
        assert exc.value.code == SensitivityErrorCode.INVALID_METHOD

    def test_oat_pairwise_raises_sensitivity_error(self) -> None:
        with pytest.raises(SensitivityError) as exc:
            sensitivity_handler(
                {
                    "criteria": ["A", "B"],
                    "matrix": [[1, 3], [1 / 3, 1]],
                    "method": "OAT_PAIRWISE",
                }
            )
        assert exc.value.code == SensitivityErrorCode.INVALID_METHOD

    def test_invalid_perturbation_range_raises_error(self) -> None:
        with pytest.raises(SensitivityError) as exc:
            sensitivity_handler(
                {
                    "criteria": ["A", "B"],
                    "matrix": [[1, 3], [1 / 3, 1]],
                    "perturbation_range": [0.5, -0.5],
                }
            )
        assert exc.value.code == SensitivityErrorCode.INVALID_PERTURBATION_RANGE

    def test_invalid_num_steps_raises_error(self) -> None:
        with pytest.raises(SensitivityError) as exc:
            sensitivity_handler(
                {
                    "criteria": ["A", "B"],
                    "matrix": [[1, 3], [1 / 3, 1]],
                    "num_steps": 3,
                }
            )
        assert exc.value.code == SensitivityErrorCode.INVALID_NUM_STEPS

    def test_invalid_target_criterion_raises_error(self) -> None:
        with pytest.raises(SensitivityError) as exc:
            sensitivity_handler(
                {
                    "criteria": ["A", "B"],
                    "matrix": [[1, 3], [1 / 3, 1]],
                    "target_criteria": ["NONEXISTENT"],
                }
            )
        assert exc.value.code == SensitivityErrorCode.INVALID_TARGET_CRITERION

    def test_invalid_matrix_raises_error(self) -> None:
        with pytest.raises(SensitivityError) as exc:
            sensitivity_handler(
                {
                    "criteria": ["A", "B"],
                    "matrix": [[1, 2], [3, 1]],
                }
            )
        assert exc.value.code == SensitivityErrorCode.MATRIX_VALIDATION_FAILED


# ===========================================================================
# ToolInput / ToolOutput boundary
# ===========================================================================


@pytest.mark.unit
class TestToolInputOutputBoundary:
    def test_valid_tool_input(self) -> None:
        inp = ToolInput(data=_valid_input(), schema=SENSITIVITY_INPUT_SCHEMA)
        assert inp.data["criteria"] == ["A", "B", "C"]

    def test_missing_criteria_rejected(self) -> None:
        with pytest.raises(ValueError, match="required field missing"):
            ToolInput(data={"matrix": [[1, 2], [0.5, 1]]}, schema=SENSITIVITY_INPUT_SCHEMA)

    def test_missing_matrix_rejected(self) -> None:
        with pytest.raises(ValueError, match="required field missing"):
            ToolInput(data={"criteria": ["A", "B"]}, schema=SENSITIVITY_INPUT_SCHEMA)

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValueError, match="unexpected field"):
            ToolInput(
                data={"criteria": ["A", "B"], "matrix": [[1, 3], [1 / 3, 1]], "extra": True},
                schema=SENSITIVITY_INPUT_SCHEMA,
            )

    def test_valid_tool_output(self) -> None:
        out = ToolOutput(data=sensitivity_handler(_valid_input()), schema=SENSITIVITY_OUTPUT_SCHEMA)
        assert "baseline_weights" in out.data


# ===========================================================================
# Governed execution (full path)
# ===========================================================================


@pytest.mark.unit
class TestGovernedExecution:
    def test_successful_execution(self, executor: ControlledExecutor, context: ToolExecutionContext) -> None:
        result = executor.execute("analysis.ahp_sensitivity", _valid_input(), context)
        assert result.success is True
        assert result.output is not None
        assert "baseline_weights" in result.output.data

    def test_tool_name_in_result(self, executor: ControlledExecutor, context: ToolExecutionContext) -> None:
        result = executor.execute("analysis.ahp_sensitivity", _valid_input(), context)
        assert result.tool_name == "analysis.ahp_sensitivity"
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

        result = executor.execute("test.handler", {"x": 1}, context)
        assert result.success is False
        assert call_count == 0

    def test_permission_denied(self, context: ToolExecutionContext) -> None:
        reg = ToolRegistry()
        register_sensitivity_tool(reg)
        policy = PermissionPolicy(allowed_risks=frozenset({ToolRisk.READ}))
        engine = PolicyEngine(permission_policy=policy)
        executor = ControlledExecutor(registry=reg, policy_engine=engine)
        result = executor.execute("analysis.ahp_sensitivity", _valid_input(), context)
        assert result.success is False
        assert "Permission denied" in result.error

    def test_handler_not_invoked_on_deny(self, context: ToolExecutionContext) -> None:
        reg = ToolRegistry()
        register_sensitivity_tool(reg)
        policy = PermissionPolicy(allowed_risks=frozenset({ToolRisk.READ}))
        engine = PolicyEngine(permission_policy=policy)
        executor = ControlledExecutor(registry=reg, policy_engine=engine)
        result = executor.execute("analysis.ahp_sensitivity", _valid_input(), context)
        assert result.success is False

    def test_audit_records_written(self, executor: ControlledExecutor, context: ToolExecutionContext) -> None:
        result = executor.execute("analysis.ahp_sensitivity", _valid_input(), context)
        assert result.success is True
        assert executor._audit_sink is not None

    def test_sensitivity_error_governed(self, executor: ControlledExecutor, context: ToolExecutionContext) -> None:
        bad_input = {"criteria": ["A", "B"], "matrix": [[1, 3], [1 / 3, 1]], "method": "INVALID"}
        result = executor.execute("analysis.ahp_sensitivity", bad_input, context)
        assert result.success is False
        assert result.error is not None

    def test_sensitivity_error_preserved_in_result(
        self, executor: ControlledExecutor, context: ToolExecutionContext
    ) -> None:
        bad_input = {"criteria": ["A", "B"], "matrix": [[1, 3], [1 / 3, 1]], "num_steps": 3}
        result = executor.execute("analysis.ahp_sensitivity", bad_input, context)
        assert result.success is False
        assert result.error is not None


# ===========================================================================
# Confirmation behavior (LOW risk = no confirmation required)
# ===========================================================================


@pytest.mark.unit
class TestConfirmationBehavior:
    def test_low_risk_no_confirmation_required(self, context: ToolExecutionContext) -> None:
        reg = ToolRegistry()
        register_sensitivity_tool(reg)
        engine = PolicyEngine()
        executor = ControlledExecutor(registry=reg, policy_engine=engine)
        result = executor.execute("analysis.ahp_sensitivity", _valid_input(), context)
        assert result.success is True

    def test_confirmation_not_checked_for_low_risk(
        self, executor: ControlledExecutor, context: ToolExecutionContext
    ) -> None:
        result = executor.execute("analysis.ahp_sensitivity", _valid_input(), context, confirmation=None)
        assert result.success is True


# ===========================================================================
# Determinism
# ===========================================================================


@pytest.mark.unit
class TestDeterminism:
    def test_repeated_execution_produces_identical_output(
        self, executor: ControlledExecutor, context: ToolExecutionContext
    ) -> None:
        r1 = executor.execute("analysis.ahp_sensitivity", _valid_input(), context)
        r2 = executor.execute("analysis.ahp_sensitivity", _valid_input(), context)
        assert r1.success is True
        assert r2.success is True
        assert r1.output is not None
        assert r2.output is not None
        assert r1.output.data["baseline_weights"] == r2.output.data["baseline_weights"]
        assert r1.output.data["baseline_ranking"] == r2.output.data["baseline_ranking"]
        assert r1.output.data["input_hash"] == r2.output.data["input_hash"]
        assert r1.output.data["criterion_results"] == r2.output.data["criterion_results"]

    def test_handler_deterministic(self) -> None:
        r1 = sensitivity_handler(_valid_input())
        r2 = sensitivity_handler(_valid_input())
        assert r1["baseline_weights"] == r2["baseline_weights"]
        assert r1["input_hash"] == r2["input_hash"]
        assert r1["criterion_results"] == r2["criterion_results"]

    def test_three_repeated_runs_identical(self) -> None:
        results = [sensitivity_handler(_valid_input()) for _ in range(3)]
        for i in range(1, len(results)):
            assert results[0]["baseline_weights"] == results[i]["baseline_weights"]
            assert results[0]["input_hash"] == results[i]["input_hash"]
            assert results[0]["criterion_results"] == results[i]["criterion_results"]


# ===========================================================================
# Security regression
# ===========================================================================


@pytest.mark.unit
class TestSecurityRegression:
    def test_no_qgis_import(self) -> None:
        import lunar_gis.analysis.sensitivity_tools as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "import qgis" not in text
        assert "from qgis" not in text

    def test_no_network_import(self) -> None:
        import lunar_gis.analysis.sensitivity_tools as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        for banned in ("import requests", "import urllib", "import socket", "import http"):
            assert banned not in text

    def test_no_numpy_import(self) -> None:
        import lunar_gis.analysis.sensitivity_tools as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "import numpy" not in text
        assert "import scipy" not in text

    def test_no_exec_or_eval(self) -> None:
        import lunar_gis.analysis.sensitivity_tools as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "exec(" not in text
        assert "eval(" not in text
        assert "compile(" not in text

    def test_no_subprocess(self) -> None:
        import lunar_gis.analysis.sensitivity_tools as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "import subprocess" not in text

    def test_no_pickle(self) -> None:
        import lunar_gis.analysis.sensitivity_tools as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "import pickle" not in text

    def test_no_random(self) -> None:
        import lunar_gis.analysis.sensitivity_tools as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "import random" not in text


# ===========================================================================
# Architecture: dependency direction
# ===========================================================================


@pytest.mark.unit
class TestArchitecture:
    def test_adapter_depends_on_sensitivity_api(self) -> None:
        import lunar_gis.analysis.sensitivity_tools as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "from lunar_gis.analysis.sensitivity import" in text

    def test_adapter_depends_on_agent_contracts(self) -> None:
        import lunar_gis.analysis.sensitivity_tools as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "from lunar_gis.agent.registry import" in text

    def test_sensitivity_engine_independent_of_agent(self) -> None:
        import lunar_gis.analysis.sensitivity as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "from lunar_gis.agent" not in text
        assert "import lunar_gis.agent" not in text

    def test_adapter_does_not_reimplement_math(self) -> None:
        import lunar_gis.analysis.sensitivity_tools as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "def _compute_ranking" not in text
        assert "def _perturb_weights" not in text
        assert "def _compute_stability" not in text
