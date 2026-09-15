"""Tests for QGIS Processing AHP sensitivity algorithm and provider.

QGIS-dependent tests (importing from lunar_gis.processing.sensitivity_algorithm
or lunar_gis.processing.provider) are marked with pytest.mark.qgis and require
a QGIS 4 runtime. They are skipped in standard CI.
"""

from __future__ import annotations

import json

import pytest

from lunar_gis.analysis.sensitivity import SensitivityError, SensitivityErrorCode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _criteria_str(criteria: list[str]) -> str:
    return json.dumps(criteria)


def _matrix_str(matrix: list[list[float]]) -> str:
    return json.dumps(matrix)


def _parse_criteria(criteria_str: str) -> list[str]:
    """Standalone criteria parser (mirrors algorithm logic)."""
    criteria = json.loads(criteria_str)
    if not isinstance(criteria, list):
        raise ValueError("Criteria must be a JSON array of strings")
    for i, c in enumerate(criteria):
        if not isinstance(c, str) or not c.strip():
            raise ValueError(f"Criteria[{i}] must be a non-empty string")
    return criteria


def _parse_matrix(matrix_str: str) -> list[list[float]]:
    """Standalone matrix parser (mirrors algorithm logic)."""
    matrix = json.loads(matrix_str)
    if not isinstance(matrix, list):
        raise ValueError("Matrix must be a JSON array of arrays")
    for i, row in enumerate(matrix):
        if not isinstance(row, list):
            raise ValueError(f"Matrix row {i} must be an array")
        for j, val in enumerate(row):
            if not isinstance(val, (int, float)):
                raise ValueError(f"Matrix[{i}][{j}] must be a number")
    return matrix


# ===========================================================================
# Input parsing (no QGIS dependency)
# ===========================================================================


@pytest.mark.unit
class TestInputParsing:
    def test_parse_valid_criteria(self) -> None:
        result = _parse_criteria(_criteria_str(["a", "b", "c"]))
        assert result == ["a", "b", "c"]

    def test_parse_criteria_not_array(self) -> None:
        with pytest.raises(ValueError, match="must be a JSON array"):
            _parse_criteria('"not an array"')

    def test_parse_criteria_empty(self) -> None:
        with pytest.raises(ValueError, match="must be a non-empty string"):
            _parse_criteria(_criteria_str([""]))

    def test_parse_criteria_whitespace(self) -> None:
        with pytest.raises(ValueError, match="must be a non-empty string"):
            _parse_criteria(_criteria_str(["   "]))

    def test_parse_criteria_not_string(self) -> None:
        with pytest.raises(ValueError, match="must be a non-empty string"):
            _parse_criteria(_criteria_str([1, 2, 3]))

    def test_parse_criteria_invalid_json(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            _parse_criteria("not json")

    def test_parse_valid_matrix(self) -> None:
        result = _parse_matrix(_matrix_str([[1, 3], [1 / 3, 1]]))
        assert result == [[1, 3], [pytest.approx(1 / 3), 1]]

    def test_parse_matrix_not_array(self) -> None:
        with pytest.raises(ValueError, match="must be a JSON array of arrays"):
            _parse_matrix('"not an array"')

    def test_parse_matrix_row_not_array(self) -> None:
        with pytest.raises(ValueError, match="Matrix row 0 must be an array"):
            _parse_matrix(_matrix_str([1, 2, 3]))

    def test_parse_matrix_non_numeric(self) -> None:
        with pytest.raises(ValueError, match="must be a number"):
            _parse_matrix(_matrix_str([["a", "b"], ["c", "d"]]))

    def test_parse_matrix_invalid_json(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            _parse_matrix("not json")


# ===========================================================================
# Sensitivity engine reference verification (no QGIS dependency)
# ===========================================================================


@pytest.mark.unit
class TestSensitivityReferenceCases:
    """Verify that parsing + engine produces correct results for known cases."""

    def test_3x3_stable_ranking(self) -> None:
        from lunar_gis.analysis.sensitivity import sensitivity_ahp

        criteria = _parse_criteria(_criteria_str(["c1", "c2", "c3"]))
        matrix = _parse_matrix(_matrix_str([[1, 3, 5], [1 / 3, 1, 3], [1 / 5, 1 / 3, 1]]))
        result = sensitivity_ahp(criteria, matrix, perturbation_range=(-0.1, 0.1))
        assert result.baseline_ranking == [0, 1, 2]
        assert len(result.criterion_results) == 3

    def test_2x2_crossover(self) -> None:
        from lunar_gis.analysis.sensitivity import sensitivity_ahp

        criteria = _parse_criteria(_criteria_str(["x", "y"]))
        matrix = _parse_matrix(_matrix_str([[1, 3], [1 / 3, 1]]))
        result = sensitivity_ahp(
            criteria,
            matrix,
            perturbation_range=(-0.5, 0.5),
            num_steps=100,
        )
        cr_x = result.criterion_results[0]
        assert len(cr_x.crossover_points) > 0

    def test_near_tie_detected(self) -> None:
        from lunar_gis.analysis.sensitivity import sensitivity_ahp

        criteria = _parse_criteria(_criteria_str(["a", "b", "c"]))
        matrix = _parse_matrix(_matrix_str([[1, 1, 3], [1, 1, 3], [1 / 3, 1 / 3, 1]]))
        result = sensitivity_ahp(criteria, matrix)
        assert len(result.near_ties) > 0


# ===========================================================================
# Error propagation (no QGIS dependency)
# ===========================================================================


@pytest.mark.unit
class TestErrorPropagation:
    def test_invalid_method(self) -> None:
        with pytest.raises(SensitivityError) as exc:
            from lunar_gis.analysis.sensitivity import sensitivity_ahp

            sensitivity_ahp(["a", "b"], [[1, 3], [1 / 3, 1]], method="INVALID")
        assert exc.value.code == SensitivityErrorCode.INVALID_METHOD

    def test_oat_pairwise_not_implemented(self) -> None:
        with pytest.raises(SensitivityError) as exc:
            from lunar_gis.analysis.sensitivity import sensitivity_ahp

            sensitivity_ahp(["a", "b"], [[1, 3], [1 / 3, 1]], method="OAT_PAIRWISE")
        assert exc.value.code == SensitivityErrorCode.INVALID_METHOD

    def test_invalid_perturbation_range(self) -> None:
        with pytest.raises(SensitivityError) as exc:
            from lunar_gis.analysis.sensitivity import sensitivity_ahp

            sensitivity_ahp(
                ["a", "b"],
                [[1, 3], [1 / 3, 1]],
                perturbation_range=(0.5, -0.5),
            )
        assert exc.value.code == SensitivityErrorCode.INVALID_PERTURBATION_RANGE

    def test_invalid_num_steps(self) -> None:
        with pytest.raises(SensitivityError) as exc:
            from lunar_gis.analysis.sensitivity import sensitivity_ahp

            sensitivity_ahp(["a", "b"], [[1, 3], [1 / 3, 1]], num_steps=3)
        assert exc.value.code == SensitivityErrorCode.INVALID_NUM_STEPS


# ===========================================================================
# Determinism (no QGIS dependency)
# ===========================================================================


@pytest.mark.unit
class TestDeterminism:
    def test_repeated_parsing_identical(self) -> None:
        criteria_str = _criteria_str(["a", "b", "c"])
        matrix_str = _matrix_str([[1, 3, 5], [1 / 3, 1, 3], [1 / 5, 1 / 3, 1]])

        c1 = _parse_criteria(criteria_str)
        m1 = _parse_matrix(matrix_str)
        c2 = _parse_criteria(criteria_str)
        m2 = _parse_matrix(matrix_str)

        assert c1 == c2
        assert m1 == m2

    def test_engine_deterministic(self) -> None:
        from lunar_gis.analysis.sensitivity import sensitivity_ahp

        criteria = ["a", "b", "c"]
        matrix = [[1, 3, 5], [1 / 3, 1, 3], [1 / 5, 1 / 3, 1]]

        r1 = sensitivity_ahp(criteria, matrix)
        r2 = sensitivity_ahp(criteria, matrix)

        assert r1.baseline_weights == r2.baseline_weights
        assert r1.input_hash == r2.input_hash
        assert r1.criterion_results == r2.criterion_results

    def test_engine_is_atomic_no_cancellation(self) -> None:
        """Engine runs to completion; cancellation/progress not implemented."""
        import inspect

        from lunar_gis.analysis.sensitivity import sensitivity_ahp

        source = inspect.getsource(sensitivity_ahp)
        assert "isCanceled" not in source
        assert "feedback" not in source.lower()


# ===========================================================================
# QGIS-dependent tests (require QGIS 4 runtime)
#
# NOTE: _serialize_result() and _build_html() in sensitivity_algorithm.py
# are module-level functions that do not use QGIS internally, but they reside
# in a module with top-level QGIS imports (qgis.core). They cannot be imported
# or tested without a QGIS runtime. The QGIS-dependent tests below cover
# algorithm metadata, provider registration, and security regression.
# Direct unit tests for _serialize_result and _build_html require QGIS and
# are skipped in standard CI. This is a known QGIS-runtime testing limitation.
# ===========================================================================


try:
    from qgis.core import (
        QgsProcessingAlgorithm,  # noqa: F401 — QGIS availability detection only
        QgsProcessingProvider,  # noqa: F401 — QGIS availability detection only
    )

    HAS_QGIS = True
except ImportError:
    HAS_QGIS = False


@pytest.mark.qgis
@pytest.mark.skipif(not HAS_QGIS, reason="QGIS runtime not available")
class TestAlgorithmMetadata:
    def test_algorithm_name(self) -> None:
        from lunar_gis.processing.sensitivity_algorithm import AHPSensitivityAlgorithm

        alg = AHPSensitivityAlgorithm()
        assert alg.name() == "ahp_sensitivity"

    def test_algorithm_display_name(self) -> None:
        from lunar_gis.processing.sensitivity_algorithm import AHPSensitivityAlgorithm

        alg = AHPSensitivityAlgorithm()
        assert alg.displayName() == "AHP Sensitivity Analysis"

    def test_algorithm_group(self) -> None:
        from lunar_gis.processing.sensitivity_algorithm import AHPSensitivityAlgorithm

        alg = AHPSensitivityAlgorithm()
        assert alg.group() == "Analysis"

    def test_algorithm_group_id(self) -> None:
        from lunar_gis.processing.sensitivity_algorithm import AHPSensitivityAlgorithm

        alg = AHPSensitivityAlgorithm()
        assert alg.groupId() == "analysis"

    def test_algorithm_help_string(self) -> None:
        from lunar_gis.processing.sensitivity_algorithm import AHPSensitivityAlgorithm

        alg = AHPSensitivityAlgorithm()
        help_str = alg.shortHelpString()
        assert "AHP" in help_str
        assert "sensitivity" in help_str.lower()

    def test_algorithm_tags(self) -> None:
        from lunar_gis.processing.sensitivity_algorithm import AHPSensitivityAlgorithm

        alg = AHPSensitivityAlgorithm()
        tags = alg.tags()
        assert "ahp" in tags
        assert "sensitivity" in tags

    def test_create_instance(self) -> None:
        from lunar_gis.processing.sensitivity_algorithm import AHPSensitivityAlgorithm

        alg = AHPSensitivityAlgorithm()
        instance = alg.createInstance()
        assert isinstance(instance, AHPSensitivityAlgorithm)
        assert instance is not alg


@pytest.mark.qgis
@pytest.mark.skipif(not HAS_QGIS, reason="QGIS runtime not available")
class TestProviderMetadata:
    def test_provider_id(self) -> None:
        from lunar_gis.processing.provider import LunarGISProvider

        provider = LunarGISProvider()
        assert provider.id() == "lunar_gis"

    def test_provider_name(self) -> None:
        from lunar_gis.processing.provider import LunarGISProvider

        provider = LunarGISProvider()
        assert provider.name() == "Lunar GIS"

    def test_provider_long_name(self) -> None:
        from lunar_gis.processing.provider import LunarGISProvider

        provider = LunarGISProvider()
        assert "Lunar GIS" in provider.longName()


@pytest.mark.qgis
@pytest.mark.skipif(not HAS_QGIS, reason="QGIS runtime not available")
class TestSecurityRegression:
    def test_no_network_import(self) -> None:
        import lunar_gis.processing.sensitivity_algorithm as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        for banned in ("import requests", "import urllib", "import socket", "import http"):
            assert banned not in text

    def test_no_numpy_import(self) -> None:
        import lunar_gis.processing.sensitivity_algorithm as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "import numpy" not in text
        assert "import scipy" not in text

    def test_no_exec_or_eval(self) -> None:
        import lunar_gis.processing.sensitivity_algorithm as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "exec(" not in text
        assert "eval(" not in text
        assert "compile(" not in text

    def test_no_subprocess(self) -> None:
        import lunar_gis.processing.sensitivity_algorithm as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "import subprocess" not in text

    def test_no_pickle(self) -> None:
        import lunar_gis.processing.sensitivity_algorithm as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "import pickle" not in text

    def test_no_random(self) -> None:
        import lunar_gis.processing.sensitivity_algorithm as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "import random" not in text

    def test_adapter_does_not_reimplement_math(self) -> None:
        import lunar_gis.processing.sensitivity_algorithm as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "def _compute_ranking" not in text
        assert "def _perturb_weights" not in text
        assert "def _compute_stability" not in text
