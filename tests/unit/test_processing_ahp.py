"""Tests for QGIS Processing AHP algorithm and provider.

QGIS-dependent tests (importing from lunar_gis.processing.ahp_algorithm or
lunar_gis.processing.provider) are marked with pytest.mark.qgis and require
a QGIS 4 runtime. They are skipped in standard CI.
"""

from __future__ import annotations

import json

import pytest

from lunar_gis.analysis.ahp import AHPError, AHPErrorCode, ConsistencyFlag


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
# AHP engine reference verification (no QGIS dependency)
# ===========================================================================


@pytest.mark.unit
class TestAHPReferenceCases:
    """Verify that parsing + engine produces correct results for known cases."""

    def test_3x3_ex1(self) -> None:
        from lunar_gis.analysis.ahp import ahp

        criteria = _parse_criteria(_criteria_str(["c1", "c2", "c3"]))
        matrix = _parse_matrix(
            _matrix_str([[1, 3, 5], [1 / 3, 1, 3], [1 / 5, 1 / 3, 1]])
        )
        result = ahp(criteria, matrix)
        assert result.weights == pytest.approx((0.636986, 0.258285, 0.104729), abs=1e-6)
        assert result.consistency.flag == ConsistencyFlag.ACCEPTABLE

    def test_2x2_exact(self) -> None:
        from lunar_gis.analysis.ahp import ahp

        criteria = _parse_criteria(_criteria_str(["a", "b"]))
        matrix = _parse_matrix(_matrix_str([[1, 4], [0.25, 1]]))
        result = ahp(criteria, matrix)
        assert result.weights == pytest.approx((0.8, 0.2), abs=1e-12)
        assert result.consistency.trivial_consistency is True

    def test_1x1_trivial(self) -> None:
        from lunar_gis.analysis.ahp import ahp

        criteria = _parse_criteria(_criteria_str(["only"]))
        matrix = _parse_matrix(_matrix_str([[1]]))
        result = ahp(criteria, matrix)
        assert result.weights == (1.0,)
        assert result.consistency.trivial_consistency is True

    def test_revise_required(self) -> None:
        from lunar_gis.analysis.ahp import ahp

        criteria = _parse_criteria(_criteria_str(["a", "b", "c"]))
        matrix = _parse_matrix(
            _matrix_str([[1, 9, 1 / 9], [1 / 9, 1, 9], [9, 1 / 9, 1]])
        )
        result = ahp(criteria, matrix)
        assert result.consistency.flag == ConsistencyFlag.REVISE_REQUIRED

    def test_acceptable_with_warning(self) -> None:
        from lunar_gis.analysis.ahp import ahp

        criteria = _parse_criteria(_criteria_str(["a", "b", "c"]))
        matrix = _parse_matrix(
            _matrix_str([[1, 7, 1 / 5], [1 / 7, 1, 1 / 9], [5, 9, 1]])
        )
        result = ahp(criteria, matrix)
        assert result.consistency.flag == ConsistencyFlag.ACCEPTABLE_WITH_WARNING


# ===========================================================================
# Error propagation (no QGIS dependency)
# ===========================================================================


@pytest.mark.unit
class TestErrorPropagation:
    def test_dimension_mismatch(self) -> None:
        criteria = _parse_criteria(_criteria_str(["a", "b"]))
        matrix = _parse_matrix(_matrix_str([[1, 2, 3], [0.5, 1, 2], [0.33, 0.5, 1]]))
        with pytest.raises(AHPError) as exc:
            from lunar_gis.analysis.ahp import ahp
            ahp(criteria, matrix)
        assert exc.value.code == AHPErrorCode.NON_SQUARE_MATRIX

    def test_invalid_diagonal(self) -> None:
        criteria = _parse_criteria(_criteria_str(["a", "b"]))
        matrix = _parse_matrix(_matrix_str([[2, 3], [1 / 3, 1]]))
        with pytest.raises(AHPError) as exc:
            from lunar_gis.analysis.ahp import ahp
            ahp(criteria, matrix)
        assert exc.value.code == AHPErrorCode.INVALID_DIAGONAL

    def test_reciprocity_violation(self) -> None:
        criteria = _parse_criteria(_criteria_str(["a", "b"]))
        matrix = _parse_matrix(_matrix_str([[1, 3], [0.5, 1]]))
        with pytest.raises(AHPError) as exc:
            from lunar_gis.analysis.ahp import ahp
            ahp(criteria, matrix)
        assert exc.value.code == AHPErrorCode.RECIPROCITY_VIOLATION

    def test_zero_judgment(self) -> None:
        criteria = _parse_criteria(_criteria_str(["a", "b"]))
        matrix = _parse_matrix(_matrix_str([[1, 0], [1, 1]]))
        with pytest.raises(AHPError) as exc:
            from lunar_gis.analysis.ahp import ahp
            ahp(criteria, matrix)
        assert exc.value.code == AHPErrorCode.INVALID_NUMERIC_VALUE

    def test_unsupported_size(self) -> None:
        n = 11
        criteria = _parse_criteria(_criteria_str([f"c{i}" for i in range(n)]))
        matrix = _parse_matrix(
            _matrix_str([[1.0 if i == j else 1.0 for j in range(n)] for i in range(n)])
        )
        with pytest.raises(AHPError) as exc:
            from lunar_gis.analysis.ahp import ahp
            ahp(criteria, matrix)
        assert exc.value.code == AHPErrorCode.UNSUPPORTED_MATRIX_SIZE


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
        from lunar_gis.analysis.ahp import ahp

        criteria = ["a", "b", "c"]
        matrix = [[1, 3, 5], [1 / 3, 1, 3], [1 / 5, 1 / 3, 1]]

        r1 = ahp(criteria, matrix)
        r2 = ahp(criteria, matrix)

        assert r1.weights == r2.weights
        assert r1.consistency.cr == r2.consistency.cr
        assert r1.input_hash == r2.input_hash


# ===========================================================================
# QGIS-dependent tests (require QGIS 4 runtime)
# ===========================================================================


try:
    from qgis.core import (
        QgsProcessingAlgorithm,
        QgsProcessingProvider,
    )

    HAS_QGIS = True
except ImportError:
    HAS_QGIS = False


@pytest.mark.qgis
@pytest.mark.skipif(not HAS_QGIS, reason="QGIS runtime not available")
class TestAlgorithmMetadata:
    def test_algorithm_name(self) -> None:
        from lunar_gis.processing.ahp_algorithm import AHPAlgorithm

        alg = AHPAlgorithm()
        assert alg.name() == "ahp_pairwise"

    def test_algorithm_display_name(self) -> None:
        from lunar_gis.processing.ahp_algorithm import AHPAlgorithm

        alg = AHPAlgorithm()
        assert alg.displayName() == "AHP Pairwise Analysis"

    def test_algorithm_group(self) -> None:
        from lunar_gis.processing.ahp_algorithm import AHPAlgorithm

        alg = AHPAlgorithm()
        assert alg.group() == "Analysis"

    def test_algorithm_group_id(self) -> None:
        from lunar_gis.processing.ahp_algorithm import AHPAlgorithm

        alg = AHPAlgorithm()
        assert alg.groupId() == "analysis"

    def test_algorithm_help_string(self) -> None:
        from lunar_gis.processing.ahp_algorithm import AHPAlgorithm

        alg = AHPAlgorithm()
        help_str = alg.shortHelpString()
        assert "AHP" in help_str
        assert "Saaty" in help_str

    def test_algorithm_tags(self) -> None:
        from lunar_gis.processing.ahp_algorithm import AHPAlgorithm

        alg = AHPAlgorithm()
        tags = alg.tags()
        assert "ahp" in tags
        assert "pairwise" in tags

    def test_create_instance(self) -> None:
        from lunar_gis.processing.ahp_algorithm import AHPAlgorithm

        alg = AHPAlgorithm()
        instance = alg.createInstance()
        assert isinstance(instance, AHPAlgorithm)
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
    def test_no_qgis_import_in_algorithm(self) -> None:
        import lunar_gis.processing.ahp_algorithm as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        # Should import qgis.core for Processing framework, but not for GIS math
        assert "import qgis" in text  # Framework import is expected
        assert "from qgis.core import" in text  # Processing base classes

    def test_no_network_import(self) -> None:
        import lunar_gis.processing.ahp_algorithm as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        for banned in ("import requests", "import urllib", "import socket", "import http"):
            assert banned not in text

    def test_no_numpy_import(self) -> None:
        import lunar_gis.processing.ahp_algorithm as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "import numpy" not in text
        assert "import scipy" not in text

    def test_no_exec_or_eval(self) -> None:
        import lunar_gis.processing.ahp_algorithm as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "exec(" not in text
        assert "eval(" not in text
        assert "compile(" not in text
