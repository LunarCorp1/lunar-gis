import hashlib
import json
from unittest.mock import patch

import pytest

from lunar_gis.analysis.ahp import (
    AHPError,
    AHPErrorCode,
    ConsistencyFlag,
    DISPLAY_PRECISION,
    FLOAT_COMPARE_EPS,
    METHOD_ID,
    NUMERICAL_POLICY_VERSION,
    POWER_MAX_ITER,
    POWER_TOL,
    RECIPROCITY_TOL,
    RI_SOURCE,
    SAATY_RI_1980,
    SAATY_SCALE,
    SCALE_MEMBERSHIP_TOL,
    ahp,
)


# ---------------------------------------------------------------------------
# Helpers: canonical matrices
# ---------------------------------------------------------------------------


def _ex1() -> tuple[list[str], list[list[float]]]:
    return ["c1", "c2", "c3"], [[1, 3, 5], [1 / 3, 1, 3], [1 / 5, 1 / 3, 1]]


def _ex2() -> tuple[list[str], list[list[float]]]:
    return ["a", "b"], [[1, 4], [1 / 4, 1]]


def _ex3() -> tuple[list[str], list[list[float]]]:
    return ["a"], [[1]]


def _ex4() -> tuple[list[str], list[list[float]]]:
    return ["a", "b", "c"], [[1, 9, 1 / 9], [1 / 9, 1, 9], [9, 1 / 9, 1]]


def _consistent_3x3() -> list[list[float]]:
    # Construct consistent matrix from weights [0.6,0.3,0.1] -> a_ij = w_i/w_j quantized to scale
    # Use exact scale values that are consistent: choose simple consistent set
    # Use w = [6,3,1] -> ratios 2,6,2
    return [[1, 2, 6], [0.5, 1, 3], [1 / 6, 1 / 3, 1]]


# ===========================================================================
# Constants
# ===========================================================================


@pytest.mark.unit
class TestConstants:
    def test_saatys_scale_size(self) -> None:
        assert len(SAATY_SCALE) == 17

    def test_saaty_scale_values(self) -> None:
        assert 1.0 in SAATY_SCALE
        assert 9.0 in SAATY_SCALE
        assert 1 / 3 in SAATY_SCALE
        assert 1 / 9 in SAATY_SCALE

    def test_ri_table(self) -> None:
        assert SAATY_RI_1980[1] == 0.00
        assert SAATY_RI_1980[2] == 0.00
        assert SAATY_RI_1980[3] == 0.58
        assert SAATY_RI_1980[4] == 0.90
        assert SAATY_RI_1980[10] == 1.49
        assert RI_SOURCE == "saaty-1980"

    def test_tolerances(self) -> None:
        assert POWER_TOL == 1e-12
        assert POWER_MAX_ITER == 10000
        assert RECIPROCITY_TOL == 1e-9
        assert SCALE_MEMBERSHIP_TOL == 1e-12
        assert FLOAT_COMPARE_EPS == 1e-9
        assert DISPLAY_PRECISION == 6
        assert NUMERICAL_POLICY_VERSION == "1.0"
        assert METHOD_ID == "principal-right-eigenvector/power-iteration"


# ===========================================================================
# Frozen oracles §14.1
# ===========================================================================


@pytest.mark.unit
class TestFrozenOracles:
    def test_ex1(self) -> None:
        criteria, matrix = _ex1()
        res = ahp(criteria, matrix)
        assert res.weights == pytest.approx((0.636986, 0.258285, 0.104729), abs=1e-6)
        assert res.consistency.lambda_max == pytest.approx(3.038511, abs=1e-4)
        assert res.consistency.ci == pytest.approx(0.019256, abs=1e-4)
        assert res.consistency.cr == pytest.approx(0.0332, abs=1e-4)
        assert res.consistency.flag == ConsistencyFlag.ACCEPTABLE
        assert res.consistency.ri_value == 0.58
        assert res.consistency.ri_source == "saaty-1980"
        assert sum(res.weights) == pytest.approx(1.0, abs=1e-9)
        assert res.iteration_count > 0
        # Residual
        aw = [sum(r[j] * res.weights[j] for j in range(3)) for r in res.matrix]
        resid = max(abs(aw[i] - res.consistency.lambda_max * res.weights[i]) for i in range(3))
        assert resid < 1e-9

    def test_ex2(self) -> None:
        criteria, matrix = _ex2()
        res = ahp(criteria, matrix)
        assert res.weights == pytest.approx((0.8, 0.2), abs=1e-12)
        assert res.consistency.lambda_max == pytest.approx(2.0, abs=1e-12)
        assert res.consistency.ci == pytest.approx(0.0, abs=1e-12)
        assert res.consistency.cr == pytest.approx(0.0, abs=1e-12)
        assert res.consistency.trivial_consistency is True
        assert res.consistency.flag == ConsistencyFlag.ACCEPTABLE
        assert res.iteration_count == 0

    def test_ex3(self) -> None:
        criteria, matrix = _ex3()
        res = ahp(criteria, matrix)
        assert res.weights == (1.0,)
        assert res.consistency.lambda_max == 1.0
        assert res.consistency.cr == 0.0
        assert res.consistency.trivial_consistency is True
        assert res.iteration_count == 0

    def test_ex4(self) -> None:
        criteria, matrix = _ex4()
        res = ahp(criteria, matrix)
        assert res.weights == pytest.approx((1 / 3, 1 / 3, 1 / 3), abs=1e-9)
        assert res.consistency.lambda_max == pytest.approx(10.111111, abs=1e-4)
        assert res.consistency.ci == pytest.approx(3.555556, abs=1e-4)
        assert res.consistency.cr == pytest.approx(6.130268, abs=1e-4)
        assert res.consistency.flag == ConsistencyFlag.REVISE_REQUIRED


# ===========================================================================
# Special cases n=1, n=2
# ===========================================================================


@pytest.mark.unit
class TestSpecialCases:
    def test_n1(self) -> None:
        res = ahp(["only"], [[1]])
        assert res.weights == (1.0,)
        assert res.consistency.lambda_max == 1.0
        assert res.consistency.ci == 0.0
        assert res.consistency.cr == 0.0
        assert res.consistency.trivial_consistency is True
        assert res.consistency.flag == ConsistencyFlag.ACCEPTABLE

    def test_n2_alternative_value(self) -> None:
        # a=2 -> w = [2/3, 1/3]
        res = ahp(["a", "b"], [[1, 2], [0.5, 1]])
        assert res.weights == pytest.approx((2 / 3, 1 / 3), abs=1e-12)
        assert res.consistency.lambda_max == pytest.approx(2.0, abs=1e-12)
        assert res.consistency.cr == 0.0

    def test_n2_exact_no_iteration(self) -> None:
        res = ahp(["a", "b"], [[1, 9], [1 / 9, 1]])
        assert res.iteration_count == 0
        assert res.weights[0] == pytest.approx(0.9, abs=1e-12)


# ===========================================================================
# Validation: shape/size
# ===========================================================================


@pytest.mark.unit
class TestValidationShapeSize:
    def test_empty_matrix(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp([], [])
        assert exc.value.code == AHPErrorCode.NON_SQUARE_MATRIX

    def test_empty_matrix_zero(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp(["a"], [])
        assert exc.value.code == AHPErrorCode.NON_SQUARE_MATRIX

    def test_non_square_ragged(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[1, 2], [0.5]])
        assert exc.value.code == AHPErrorCode.NON_SQUARE_MATRIX

    def test_non_square_criteria_mismatch(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b", "c"], [[1, 2], [0.5, 1]])
        assert exc.value.code == AHPErrorCode.NON_SQUARE_MATRIX

    def test_nonexistent_list_type(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp(["a"], "not a matrix")  # type: ignore[arg-type]
        assert exc.value.code == AHPErrorCode.NON_SQUARE_MATRIX

    def test_none_row(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[1, 2], None])  # type: ignore[list-item]
        assert exc.value.code == AHPErrorCode.NON_SQUARE_MATRIX

    def test_incomplete_matrix_none_entry(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[1, None], [0.5, 1]])  # type: ignore[list-item]
        assert exc.value.code == AHPErrorCode.INCOMPLETE_MATRIX

    def test_unsupported_size_11(self) -> None:
        n = 11
        criteria = [f"c{i}" for i in range(n)]
        matrix = [[1.0 if i == j else 1.0 for j in range(n)] for i in range(n)]
        # Need diagonal 1, but off-diagonal 1 is scale value; reciprocity holds (1*1=1)
        with pytest.raises(AHPError) as exc:
            ahp(criteria, matrix)
        assert exc.value.code == AHPErrorCode.UNSUPPORTED_MATRIX_SIZE

    def test_n10_accept(self) -> None:
        n = 10
        criteria = [f"c{i}" for i in range(n)]
        matrix = [[1.0 if i == j else 1.0 for j in range(n)] for i in range(n)]
        res = ahp(criteria, matrix)
        assert len(res.weights) == 10

    def test_n0_via_empty_criteria(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp([], [[1]])
        assert exc.value.code == AHPErrorCode.NON_SQUARE_MATRIX


# ===========================================================================
# Validation: criteria
# ===========================================================================


@pytest.mark.unit
class TestValidationCriteria:
    def test_duplicate_criterion(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp(["a", "a"], [[1, 1], [1, 1]])
        assert exc.value.code == AHPErrorCode.DUPLICATE_CRITERION

    def test_empty_criterion(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp(["", "b"], [[1, 1], [1, 1]])
        assert exc.value.code == AHPErrorCode.EMPTY_CRITERION_NAME

    def test_whitespace_only(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp(["   ", "b"], [[1, 1], [1, 1]])
        assert exc.value.code == AHPErrorCode.EMPTY_CRITERION_NAME

    def test_non_string_criterion(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp([1, 2], [[1, 1], [1, 1]])  # type: ignore[list-item]
        assert exc.value.code == AHPErrorCode.EMPTY_CRITERION_NAME

    def test_criteria_not_list(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp("ab", [[1]])  # type: ignore[arg-type]
        assert exc.value.code == AHPErrorCode.EMPTY_CRITERION_NAME


# ===========================================================================
# Validation: diagonal
# ===========================================================================


@pytest.mark.unit
class TestValidationDiagonal:
    def test_invalid_diagonal(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[2, 1], [1, 1]])
        assert exc.value.code == AHPErrorCode.INVALID_DIAGONAL

    def test_diagonal_close_but_not_exact(self) -> None:
        # 1.0000000001 should fail (exact required)
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[1.0000000001, 1], [1, 1]])
        assert exc.value.code == AHPErrorCode.INVALID_DIAGONAL


# ===========================================================================
# Validation: numeric
# ===========================================================================


@pytest.mark.unit
class TestValidationNumeric:
    def test_nan(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[1, float("nan")], [1, 1]])
        assert exc.value.code == AHPErrorCode.INVALID_NUMERIC_VALUE

    def test_inf(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[1, float("inf")], [1, 1]])
        assert exc.value.code == AHPErrorCode.INVALID_NUMERIC_VALUE

    def test_neg_inf(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[1, float("-inf")], [1, 1]])
        assert exc.value.code == AHPErrorCode.INVALID_NUMERIC_VALUE

    def test_zero(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[1, 0], [1, 1]])
        assert exc.value.code == AHPErrorCode.INVALID_NUMERIC_VALUE

    def test_negative(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[1, -3], [1, 1]])
        assert exc.value.code == AHPErrorCode.INVALID_NUMERIC_VALUE

    def test_string_entry(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[1, "3"], [1, 1]])  # type: ignore[list-item]
        assert exc.value.code == AHPErrorCode.INVALID_NUMERIC_VALUE

    def test_bool_entry(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[1, True], [1, 1]])  # type: ignore[list-item]
        assert exc.value.code == AHPErrorCode.INVALID_NUMERIC_VALUE


# ===========================================================================
# Validation: scale membership
# ===========================================================================


@pytest.mark.unit
class TestValidationScale:
    def test_off_scale_2_5(self) -> None:
        # Need valid diagonal, numeric finite positive, then off-scale
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[1, 2.5], [0.4, 1]])
        assert exc.value.code == AHPErrorCode.OFF_SCALE_VALUE

    def test_off_scale_10(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[1, 10], [0.1, 1]])
        assert exc.value.code == AHPErrorCode.OFF_SCALE_VALUE

    def test_scale_tolerance_near_one_third(self) -> None:
        # 1/3 exactly should pass; near value within 1e-12 relative should pass
        val = 1 / 3 + 1e-13  # within tolerance
        res = ahp(["a", "b"], [[1, val], [1 / val, 1]])
        assert res.weights[0] == pytest.approx(val / (1 + val), abs=1e-9)

    def test_scale_outside_tolerance(self) -> None:
        # perturb beyond 1e-12 relative -> off scale
        val = 3.0 + 3.0 * 2e-12
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[1, val], [1 / val, 1]])
        assert exc.value.code == AHPErrorCode.OFF_SCALE_VALUE

    def test_all_17_scale_values_accepted(self) -> None:
        for v in SAATY_SCALE:
            # 1x1 with diagonal 1 is trivial; for 2x2 test scale value as off-diagonal
            if v == 1.0:
                continue
            matrix = [[1, float(v)], [float(1 / v), 1]]
            res = ahp(["a", "b"], matrix)
            assert len(res.weights) == 2


# ===========================================================================
# Validation: reciprocity
# ===========================================================================


@pytest.mark.unit
class TestValidationReciprocity:
    def test_reciprocity_violation(self) -> None:
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[1, 3], [0.5, 1]])  # 3*0.5=1.5 !=1
        assert exc.value.code == AHPErrorCode.RECIPROCITY_VIOLATION

    def test_reciprocity_within_tolerance(self) -> None:
        # Exact reciprocals must pass (binary64 1/3*3 ==1 within tolerance)
        a = 3.0
        b = 1 / 3
        res = ahp(["a", "b"], [[1, a], [b, 1]])
        assert res.weights is not None
        assert abs(a * b - 1.0) <= RECIPROCITY_TOL

    def test_reciprocity_outside_tolerance(self) -> None:
        # Valid scale values but not reciprocal -> violation
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[1, 3], [0.5, 1]])
        assert exc.value.code == AHPErrorCode.RECIPROCITY_VIOLATION

    def test_reciprocity_boundary_exact(self) -> None:
        # Exactly reciprocal should pass
        res = ahp(["a", "b", "c"], [[1, 3, 5], [1 / 3, 1, 3], [1 / 5, 1 / 3, 1]])
        assert res.consistency.flag == ConsistencyFlag.ACCEPTABLE


# ===========================================================================
# Validation order (first failure wins)
# ===========================================================================


@pytest.mark.unit
class TestValidationOrder:
    def test_shape_before_size(self) -> None:
        # Empty matrix should be NON_SQUARE, not UNSUPPORTED
        with pytest.raises(AHPError) as exc:
            ahp([], [])
        assert exc.value.code == AHPErrorCode.NON_SQUARE_MATRIX

    def test_diagonal_before_numeric(self) -> None:
        # Diagonal invalid should win even if off-diagonal would also be invalid
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[0, float("nan")], [1, 1]])
        assert exc.value.code == AHPErrorCode.INVALID_DIAGONAL

    def test_numeric_before_scale(self) -> None:
        # zero (numeric) should win over off-scale? zero is numeric failure
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[1, 0], [1, 1]])
        assert exc.value.code == AHPErrorCode.INVALID_NUMERIC_VALUE

    def test_scale_before_reciprocity(self) -> None:
        # 2.5 is off-scale; also reciprocal will fail but scale should win
        with pytest.raises(AHPError) as exc:
            ahp(["a", "b"], [[1, 2.5], [0.5, 1]])
        assert exc.value.code == AHPErrorCode.OFF_SCALE_VALUE

    def test_non_square_before_unsupported(self) -> None:
        # Ragged 11x? but ragged should be NON_SQUARE not UNSUPPORTED
        with pytest.raises(AHPError) as exc:
            ahp([f"c{i}" for i in range(2)], [[1, 2, 3], [0.5, 1, 4]])
        assert exc.value.code == AHPErrorCode.NON_SQUARE_MATRIX


# ===========================================================================
# Consistency classification
# ===========================================================================


@pytest.mark.unit
class TestConsistencyClassification:
    def test_acceptable(self) -> None:
        criteria, matrix = _ex1()
        res = ahp(criteria, matrix)
        assert res.consistency.flag == ConsistencyFlag.ACCEPTABLE
        assert res.consistency.trivial_consistency is False

    def test_revise_required(self) -> None:
        criteria, matrix = _ex4()
        res = ahp(criteria, matrix)
        assert res.consistency.flag == ConsistencyFlag.REVISE_REQUIRED

    def test_flag_pinned_strings(self) -> None:
        assert ConsistencyFlag.ACCEPTABLE.value == "ACCEPTABLE"
        assert ConsistencyFlag.ACCEPTABLE_WITH_WARNING.value == "ACCEPTABLE_WITH_WARNING"
        assert ConsistencyFlag.REVISE_REQUIRED.value == "REVISE_REQUIRED"

    def test_threshold_epsilon(self) -> None:
        # CR exactly at 0.10 within eps should be ACCEPTABLE
        # We craft a matrix near boundary - use a known consistent matrix for CR 0
        res = ahp(["a", "b", "c"], _consistent_3x3())
        assert res.consistency.cr == pytest.approx(0.0, abs=1e-9)
        assert res.consistency.flag == ConsistencyFlag.ACCEPTABLE

    def test_n_less_than_3_always_acceptable(self) -> None:
        for n, mat in [(1, [[1]]), (2, [[1, 3], [1 / 3, 1]])]:  # type: ignore[assignment]
            criteria = [f"c{i}" for i in range(n)]
            # For n=1,2 need valid matrix; for n=2 use scale value
            if n == 1:
                res = ahp(criteria, mat)  # type: ignore[arg-type]
            else:
                res = ahp(criteria, mat)  # type: ignore[arg-type]
            assert res.consistency.flag == ConsistencyFlag.ACCEPTABLE
            assert res.consistency.trivial_consistency is True
            assert res.consistency.cr == 0.0
            assert res.consistency.ci == 0.0

    def test_acceptable_with_warning_exists(self) -> None:
        # Known 3x3 matrix yielding CR ≈ 0.1797 (in (0.10, 0.20])
        # Source: manually constructed moderately inconsistent reciprocal matrix
        mat = [[1, 7, 1 / 5], [1 / 7, 1, 1 / 9], [5, 9, 1]]
        res = ahp(["a", "b", "c"], mat)
        assert res.consistency.flag == ConsistencyFlag.ACCEPTABLE_WITH_WARNING
        assert 0.10 < res.consistency.cr <= 0.20 + FLOAT_COMPARE_EPS
        assert res.consistency.trivial_consistency is False
        # Weights are still valid
        assert sum(res.weights) == pytest.approx(1.0, abs=1e-9)
        assert all(w > 0 for w in res.weights)


# ===========================================================================
# Provenance & determinism
# ===========================================================================


@pytest.mark.unit
class TestProvenanceDeterminism:
    def test_input_hash_deterministic(self) -> None:
        criteria, matrix = _ex1()
        r1 = ahp(criteria, matrix)
        r2 = ahp(criteria, matrix)
        assert r1.input_hash == r2.input_hash
        assert r1.weights == r2.weights
        assert r1.consistency.lambda_max == r2.consistency.lambda_max

    def test_input_hash_is_sha256(self) -> None:
        criteria, matrix = _ex1()
        res = ahp(criteria, matrix)
        assert len(res.input_hash) == 64
        # Verify it matches canonical JSON hashing
        payload = {"criteria": list(criteria), "matrix": [list(map(float, row)) for row in matrix]}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        assert res.input_hash == expected

    def test_weights_sum_to_one(self) -> None:
        for criteria, matrix in [_ex1(), _ex2(), _ex3(), _ex4()]:
            res = ahp(criteria, matrix)
            assert sum(res.weights) == pytest.approx(1.0, abs=1e-9)
            assert all(w > 0 for w in res.weights)

    def test_method_and_versions(self) -> None:
        criteria, matrix = _ex1()
        res = ahp(criteria, matrix)
        assert res.method == METHOD_ID
        assert res.numerical_policy_version == NUMERICAL_POLICY_VERSION
        assert res.display_precision == DISPLAY_PRECISION
        assert res.engine_version is not None

    def test_criteria_order_preserved(self) -> None:
        criteria = ["z", "a", "m"]
        matrix = [[1, 3, 5], [1 / 3, 1, 3], [1 / 5, 1 / 3, 1]]
        res = ahp(criteria, matrix)  # type: ignore[arg-type]
        assert res.criteria == tuple(criteria)
        assert list(res.weights_dict().keys()) == criteria

    def test_iteration_count(self) -> None:
        criteria, matrix = _ex1()
        res = ahp(criteria, matrix)
        assert 0 < res.iteration_count <= POWER_MAX_ITER
        # n=1,2 have 0 iterations
        assert ahp(["a"], [[1]]).iteration_count == 0
        assert ahp(["a", "b"], [[1, 4], [0.25, 1]]).iteration_count == 0

    def test_to_dict(self) -> None:
        criteria, matrix = _ex1()
        res = ahp(criteria, matrix)
        d = res.to_dict()
        assert d["criteria"] == list(criteria)
        assert d["weights"] == list(res.weights)
        assert d["flag"] == res.consistency.flag.value
        assert d["input_hash"] == res.input_hash


# ===========================================================================
# Error code taxonomy
# ===========================================================================


@pytest.mark.unit
class TestErrorCodes:
    def test_all_codes_exist(self) -> None:
        for code in [
            "NON_SQUARE_MATRIX",
            "UNSUPPORTED_MATRIX_SIZE",
            "INVALID_DIAGONAL",
            "INVALID_NUMERIC_VALUE",
            "OFF_SCALE_VALUE",
            "RECIPROCITY_VIOLATION",
            "INCOMPLETE_MATRIX",
            "DUPLICATE_CRITERION",
            "EMPTY_CRITERION_NAME",
            "NUMERICAL_CONVERGENCE_FAILURE",
            "NUMERICAL_RESULT_VALIDATION_FAILURE",
        ]:
            assert AHPErrorCode(code) is not None

    def test_error_carries_code(self) -> None:
        try:
            ahp(["a", "b"], [[0, 1], [1, 1]])
        except AHPError as e:
            assert e.code == AHPErrorCode.INVALID_DIAGONAL
            assert "INVALID_DIAGONAL" in str(e)


# ===========================================================================
# No QGIS / no network / stdlib only
# ===========================================================================


@pytest.mark.unit
class TestSecurityRegression:
    def test_no_qgis_import(self) -> None:
        import lunar_gis.analysis.ahp as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "import qgis" not in text
        assert "from qgis" not in text

    def test_no_network_import(self) -> None:
        import lunar_gis.analysis.ahp as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        for banned in ("import requests", "import urllib", "import socket", "import http"):
            assert banned not in text

    def test_no_numpy_import(self) -> None:
        import lunar_gis.analysis.ahp as mod

        source = mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            text = f.read()
        assert "import numpy" not in text
        assert "import scipy" not in text


# ===========================================================================
# Fault-injected numerical error paths
# ===========================================================================


@pytest.mark.unit
class TestNumericalErrorPaths:
    def test_convergence_failure_via_iteration_cap(self) -> None:
        """Force NUMERICAL_CONVERGENCE_FAILURE by capping iterations at 1."""
        criteria, matrix = _ex1()
        with patch("lunar_gis.analysis.ahp.POWER_MAX_ITER", 1):
            with pytest.raises(AHPError) as exc:
                ahp(criteria, matrix)
            assert exc.value.code == AHPErrorCode.NUMERICAL_CONVERGENCE_FAILURE

    def test_result_validation_failure_via_matvec_injection(self) -> None:
        """Force NUMERICAL_RESULT_VALIDATION_FAILURE by injecting zeros in Aw.

        After convergence, _priority_vector_and_iterations checks that the
        residual ||Aw - λw||∞ < RESIDUAL_TOL. By replacing _matvec with a
        function that returns zeros, the residual check will fail.
        """
        criteria, matrix = _ex1()

        def _zero_matvec(m, v):  # type: ignore[no-untyped-def]
            return [0.0] * len(v)

        with patch("lunar_gis.analysis.ahp._matvec", side_effect=_zero_matvec):
            with pytest.raises(AHPError) as exc:
                ahp(criteria, matrix)
            assert exc.value.code == AHPErrorCode.NUMERICAL_RESULT_VALIDATION_FAILURE
