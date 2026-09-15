"""Tests for the deterministic AHP sensitivity analysis engine.

Pure stdlib, no QGIS/network/numpy/scipy. Covers:
  - Baseline correctness and immutability
  - OAT weight perturbation determinism
  - Ranking policy (ties, near-ties, crossovers)
  - Stability intervals
  - Consistency interaction
  - Provenance fields
  - Input validation / error taxonomy
  - OAT_PAIRWISE rejection
  - Security / architecture regression
  - Frozen oracle cases
"""

from __future__ import annotations


import pytest

from lunar_gis.analysis.ahp import (
    FLOAT_COMPARE_EPS,
    ahp,
)
from lunar_gis.analysis.sensitivity import (
    CONSISTENCY_POLICY_VERSION,
    NEAR_TIE_TOL,
    RANKING_POLICY_VERSION,
    SENSITIVITY_POLICY_VERSION,
    SensitivityError,
    SensitivityErrorCode,
    SensitivityMethod,
    _compute_ranking,
    _detect_crossovers,
    _detect_near_ties,
    _perturb_weights_oat,
    _rankings_equal,
    sensitivity_ahp,
)


# ---------------------------------------------------------------------------
# Oracle matrices
# ---------------------------------------------------------------------------

# Oracle 1: 3x3 consistent matrix
ORACLE1_CRITERIA = ["A", "B", "C"]
ORACLE1_MATRIX = [
    [1, 3, 5],
    [1 / 3, 1, 3],
    [1 / 5, 1 / 3, 1],
]

# Oracle 2: 3x3 near-tie matrix (A and B have equal weights)
ORACLE2_CRITERIA = ["A", "B", "C"]
ORACLE2_MATRIX = [
    [1, 1, 3],
    [1, 1, 3],
    [1 / 3, 1 / 3, 1],
]

# Oracle 3: 2x2 exact formula
ORACLE3_CRITERIA = ["X", "Y"]
ORACLE3_MATRIX = [
    [1, 3],
    [1 / 3, 1],
]


# ---------------------------------------------------------------------------
# TestConstants
# ---------------------------------------------------------------------------


class TestSensitivityConstants:
    def test_near_tie_tol(self) -> None:
        assert NEAR_TIE_TOL == 1e-6

    def test_sensitivity_policy_version(self) -> None:
        assert SENSITIVITY_POLICY_VERSION == "1.0"

    def test_ranking_policy_version(self) -> None:
        assert RANKING_POLICY_VERSION == "1.0"

    def test_consistency_policy_version(self) -> None:
        assert CONSISTENCY_POLICY_VERSION == "1.0"


# ---------------------------------------------------------------------------
# TestRanking
# ---------------------------------------------------------------------------


class TestRanking:
    def test_descending_order(self) -> None:
        weights = [0.6, 0.3, 0.1]
        ranking = _compute_ranking(weights)
        assert ranking == [0, 1, 2]

    def test_equal_weights_tie(self) -> None:
        weights = [1 / 3, 1 / 3, 1 / 3]
        ranking = _compute_ranking(weights)
        assert ranking == [0, 0, 0]

    def test_two_tied(self) -> None:
        weights = [0.5, 0.5, 0.0]
        ranking = _compute_ranking(weights)
        assert ranking[0] == ranking[1]
        assert ranking[2] > ranking[0]

    def test_three_way_tie(self) -> None:
        weights = [0.4, 0.4, 0.4]
        ranking = _compute_ranking(weights)
        assert ranking == [0, 0, 0]

    def test_near_tie_detected(self) -> None:
        criteria = ["A", "B", "C"]
        weights = [0.4, 0.4 + 1e-7, 0.2]
        near = _detect_near_ties(criteria, weights)
        assert ("A", "B") in near

    def test_no_near_ties(self) -> None:
        criteria = ["A", "B", "C"]
        weights = [0.6, 0.3, 0.1]
        near = _detect_near_ties(criteria, weights)
        assert near == []

    def test_rankings_equal(self) -> None:
        assert _rankings_equal([0, 1, 2], [0, 1, 2])
        assert not _rankings_equal([0, 1, 2], [1, 0, 2])


# ---------------------------------------------------------------------------
# TestOATWeightPerturbation
# ---------------------------------------------------------------------------


class TestOATWeightPerturbation:
    def test_zero_perturbation(self) -> None:
        weights = [0.6, 0.3, 0.1]
        perturbed = _perturb_weights_oat(weights, 0, 0.0)
        for i in range(3):
            assert abs(perturbed[i] - weights[i]) < FLOAT_COMPARE_EPS

    def test_perturbation_sums_to_one(self) -> None:
        weights = [0.6, 0.3, 0.1]
        for delta in [-0.2, -0.1, 0.0, 0.1, 0.2]:
            perturbed = _perturb_weights_oat(weights, 0, delta)
            assert abs(sum(perturbed) - 1.0) < 1e-6

    def test_only_target_changes(self) -> None:
        weights = [0.6, 0.3, 0.1]
        perturbed = _perturb_weights_oat(weights, 0, 0.1)
        assert abs(perturbed[0] - 0.7) < 1e-6
        # Other weights maintain their ratio
        ratio = weights[1] / weights[2]
        new_ratio = perturbed[1] / perturbed[2]
        assert abs(ratio - new_ratio) < 1e-6

    def test_positive_perturbation(self) -> None:
        weights = [0.6, 0.3, 0.1]
        perturbed = _perturb_weights_oat(weights, 0, 0.1)
        assert perturbed[0] > weights[0]

    def test_negative_perturbation(self) -> None:
        weights = [0.6, 0.3, 0.1]
        perturbed = _perturb_weights_oat(weights, 0, -0.1)
        assert perturbed[0] < weights[0]


# ---------------------------------------------------------------------------
# TestBaseline
# ---------------------------------------------------------------------------


class TestBaseline:
    def test_baseline_agrees_with_ahp(self) -> None:
        result = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX)
        baseline = ahp(ORACLE1_CRITERIA, [list(row) for row in ORACLE1_MATRIX])
        assert result.baseline_weights == list(baseline.weights)

    def test_baseline_not_mutated(self) -> None:
        original_matrix = [list(row) for row in ORACLE1_MATRIX]
        matrix_copy = [list(row) for row in original_matrix]
        sensitivity_ahp(ORACLE1_CRITERIA, original_matrix)
        assert original_matrix == matrix_copy

    def test_criteria_not_mutated(self) -> None:
        criteria = list(ORACLE1_CRITERIA)
        criteria_copy = list(criteria)
        sensitivity_ahp(criteria, ORACLE1_MATRIX)
        assert criteria == criteria_copy

    def test_baseline_ranking(self) -> None:
        result = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX)
        assert result.baseline_ranking == [0, 1, 2]


# ---------------------------------------------------------------------------
# TestDeterminism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_identical_inputs_identical_outputs(self) -> None:
        r1 = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX)
        r2 = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX)
        assert r1.baseline_weights == r2.baseline_weights
        assert r1.baseline_ranking == r2.baseline_ranking
        assert r1.input_hash == r2.input_hash

    def test_deterministic_perturbation_sequence(self) -> None:
        r1 = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX, num_steps=10)
        r2 = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX, num_steps=10)
        assert r1.criterion_results[0].perturbation_values == r2.criterion_results[0].perturbation_values

    def test_three_repeated_runs_identical(self) -> None:
        """Determinism: 3+ repeated runs produce identical results."""
        results = [sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX, num_steps=15) for _ in range(3)]
        for i in range(1, len(results)):
            assert results[0].baseline_weights == results[i].baseline_weights
            assert results[0].baseline_ranking == results[i].baseline_ranking
            assert results[0].input_hash == results[i].input_hash
            for j in range(len(results[0].criterion_results)):
                r0 = results[0].criterion_results[j]
                rj = results[i].criterion_results[j]
                assert r0.perturbation_values == rj.perturbation_values
                assert r0.perturbed_weights == rj.perturbed_weights
                assert r0.perturbed_rankings == rj.perturbed_rankings
                assert r0.crossover_points == rj.crossover_points
                assert r0.stability_lower == rj.stability_lower
                assert r0.stability_upper == rj.stability_upper

    def test_determinism_across_different_step_counts(self) -> None:
        """Determinism: different step counts produce consistent results."""
        for steps in [5, 10, 20, 50]:
            r1 = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX, num_steps=steps)
            r2 = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX, num_steps=steps)
            assert r1.baseline_weights == r2.baseline_weights
            assert r1.input_hash == r2.input_hash
            for j in range(3):
                assert r1.criterion_results[j].perturbed_weights == r2.criterion_results[j].perturbed_weights

    def test_determinism_extended_oat(self) -> None:
        """Determinism: extended OAT sweep with many steps."""
        r1 = sensitivity_ahp(
            ORACLE1_CRITERIA,
            ORACLE1_MATRIX,
            perturbation_range=(-0.4, 0.4),
            num_steps=50,
        )
        r2 = sensitivity_ahp(
            ORACLE1_CRITERIA,
            ORACLE1_MATRIX,
            perturbation_range=(-0.4, 0.4),
            num_steps=50,
        )
        for j in range(3):
            assert r1.criterion_results[j].perturbed_weights == r2.criterion_results[j].perturbed_weights
            assert r1.criterion_results[j].perturbed_rankings == r2.criterion_results[j].perturbed_rankings

    def test_no_randomness_in_module(self) -> None:
        """No random module usage anywhere in sensitivity source."""
        import lunar_gis.analysis.sensitivity as mod

        source = open(mod.__file__).read()  # noqa: SIM115
        assert "import random" not in source
        assert "random.random" not in source
        assert "random.seed" not in source


# ---------------------------------------------------------------------------
# TestStabilityInterval
# ---------------------------------------------------------------------------


class TestStabilityInterval:
    def test_no_crossover_full_range(self) -> None:
        result = sensitivity_ahp(
            ORACLE3_CRITERIA,
            ORACLE3_MATRIX,
            perturbation_range=(-0.1, 0.1),
        )
        # With small range, no crossover expected
        cr = result.criterion_results[0]
        assert cr.stability_lower >= -0.1 - FLOAT_COMPARE_EPS
        assert cr.stability_upper <= 0.1 + FLOAT_COMPARE_EPS

    def test_crossover_detected(self) -> None:
        result = sensitivity_ahp(
            ORACLE3_CRITERIA,
            ORACLE3_MATRIX,
            perturbation_range=(-0.5, 0.5),
            num_steps=50,
        )
        # For 2x2, crossover at w_x = w_y = 0.5, so delta = -0.25
        cr = result.criterion_results[0]
        # Should have crossover points
        assert len(cr.crossover_points) > 0

    def test_stability_interval_bounds(self) -> None:
        result = sensitivity_ahp(
            ORACLE1_CRITERIA,
            ORACLE1_MATRIX,
            perturbation_range=(-0.5, 0.5),
            num_steps=50,
        )
        cr_a = result.criterion_results[0]
        # Stability interval should be within perturbation range
        assert cr_a.stability_lower >= -0.5 - FLOAT_COMPARE_EPS
        assert cr_a.stability_upper <= 0.5 + FLOAT_COMPARE_EPS

    def test_stability_interval_non_decreasing(self) -> None:
        """stability_lower <= stability_upper always."""
        result = sensitivity_ahp(
            ORACLE1_CRITERIA,
            ORACLE1_MATRIX,
            perturbation_range=(-0.5, 0.5),
            num_steps=50,
        )
        for cr in result.criterion_results:
            assert cr.stability_lower <= cr.stability_upper + FLOAT_COMPARE_EPS

    def test_stability_interval_full_range_when_all_stable(self) -> None:
        """When no crossover occurs, interval spans the full perturbation range."""
        result = sensitivity_ahp(
            ORACLE1_CRITERIA,
            ORACLE1_MATRIX,
            perturbation_range=(-0.1, 0.1),
            num_steps=10,
        )
        for cr in result.criterion_results:
            # All rankings should match baseline (no crossover)
            assert len(cr.crossover_points) == 0
            # Interval should span approximately the full range
            assert cr.stability_lower <= -0.1 + FLOAT_COMPARE_EPS
            assert cr.stability_upper >= 0.1 - FLOAT_COMPARE_EPS


# ---------------------------------------------------------------------------
# TestCrossoverDetection
# ---------------------------------------------------------------------------


class TestCrossoverDetection:
    def test_no_crossover(self) -> None:
        values = [0.0, 0.01, 0.02]
        rankings = [[0, 1, 2], [0, 1, 2], [0, 1, 2]]
        baseline = [0, 1, 2]
        crossovers = _detect_crossovers(values, rankings, baseline)
        assert crossovers == []

    def test_single_crossover(self) -> None:
        values = [0.0, -0.05, -0.1, -0.15]
        rankings = [[0, 1, 2], [0, 1, 2], [0, 1, 2], [1, 0, 2]]
        baseline = [0, 1, 2]
        crossovers = _detect_crossovers(values, rankings, baseline)
        assert crossovers == [-0.15]

    def test_multiple_crossovers(self) -> None:
        values = [-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3]
        rankings = [
            [2, 0, 1],  # crossover from baseline
            [1, 0, 2],  # crossover from baseline
            [0, 1, 2],  # same as baseline
            [0, 1, 2],  # baseline
            [0, 1, 2],  # same as baseline
            [0, 2, 1],  # crossover from baseline
            [2, 0, 1],  # crossover from baseline
        ]
        baseline = [0, 1, 2]
        crossovers = _detect_crossovers(values, rankings, baseline)
        assert -0.3 in crossovers
        assert -0.2 in crossovers
        assert 0.2 in crossovers
        assert 0.3 in crossovers


# ---------------------------------------------------------------------------
# TestConsistencyInteraction
# ---------------------------------------------------------------------------


class TestConsistencyInteraction:
    def test_baseline_consistency_preserved(self) -> None:
        result = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX)
        for cr in result.criterion_results:
            for flag in cr.consistency_flags:
                # Consistency flag should be one of the valid values
                assert flag in ("ACCEPTABLE", "ACCEPTABLE_WITH_WARNING", "REVISE_REQUIRED")

    def test_consistency_ratios_present(self) -> None:
        result = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX)
        for cr in result.criterion_results:
            assert len(cr.consistency_ratios) == result.num_steps
            for ratio in cr.consistency_ratios:
                assert isinstance(ratio, float)

    def test_no_silent_filtering(self) -> None:
        result = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX)
        for cr in result.criterion_results:
            assert len(cr.perturbed_weights) == result.num_steps
            assert len(cr.consistency_flags) == result.num_steps


# ---------------------------------------------------------------------------
# TestProvenance
# ---------------------------------------------------------------------------


class TestProvenance:
    def test_required_fields(self) -> None:
        result = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX)
        assert result.sensitivity_policy_version == "1.0"
        assert result.numerical_policy_version == "1.0"
        assert result.engine_version is not None
        assert result.input_hash is not None
        assert result.method == SensitivityMethod.OAT_WEIGHT
        assert result.perturbation_range == (-0.3, 0.3)
        assert result.num_steps == 20
        assert result.ranking_policy_version == "1.0"
        assert result.consistency_policy_version == "1.0"

    def test_input_hash_deterministic(self) -> None:
        r1 = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX)
        r2 = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX)
        assert r1.input_hash == r2.input_hash

    def test_input_hash_matches_ahp(self) -> None:
        result = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX)
        baseline = ahp(ORACLE1_CRITERIA, [list(row) for row in ORACLE1_MATRIX])
        assert result.input_hash == baseline.input_hash

    def test_criteria_order_preserved(self) -> None:
        result = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX)
        assert result.criteria == ORACLE1_CRITERIA

    def test_near_ties_recorded(self) -> None:
        result = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX)
        assert isinstance(result.near_ties, list)

    def test_target_criteria_recorded(self) -> None:
        result = sensitivity_ahp(
            ORACLE1_CRITERIA,
            ORACLE1_MATRIX,
            target_criteria=["A"],
        )
        assert result.target_criteria == ["A"]

    def test_target_criteria_none(self) -> None:
        result = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX)
        assert result.target_criteria is None


# ---------------------------------------------------------------------------
# TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_empty_criteria(self) -> None:
        with pytest.raises(SensitivityError) as exc_info:
            sensitivity_ahp([], [[1]])
        assert exc_info.value.code == SensitivityErrorCode.INVALID_INPUT

    def test_single_criterion(self) -> None:
        with pytest.raises(SensitivityError) as exc_info:
            sensitivity_ahp(["A"], [[1]])
        assert exc_info.value.code == SensitivityErrorCode.INVALID_INPUT

    def test_invalid_method(self) -> None:
        with pytest.raises(SensitivityError) as exc_info:
            sensitivity_ahp(
                ORACLE1_CRITERIA,
                ORACLE1_MATRIX,
                method="INVALID",
            )
        assert exc_info.value.code == SensitivityErrorCode.INVALID_METHOD

    def test_oat_pairwise_rejected(self) -> None:
        """OAT_PAIRWISE raises SensitivityError until implemented."""
        with pytest.raises(SensitivityError) as exc_info:
            sensitivity_ahp(
                ORACLE1_CRITERIA,
                ORACLE1_MATRIX,
                method="OAT_PAIRWISE",
            )
        assert exc_info.value.code == SensitivityErrorCode.INVALID_METHOD
        assert "not yet implemented" in str(exc_info.value.message)

    def test_perturbation_range_min_ge_max(self) -> None:
        with pytest.raises(SensitivityError) as exc_info:
            sensitivity_ahp(
                ORACLE1_CRITERIA,
                ORACLE1_MATRIX,
                perturbation_range=(0.5, -0.5),
            )
        assert exc_info.value.code == SensitivityErrorCode.INVALID_PERTURBATION_RANGE

    def test_perturbation_range_out_of_bounds(self) -> None:
        with pytest.raises(SensitivityError) as exc_info:
            sensitivity_ahp(
                ORACLE1_CRITERIA,
                ORACLE1_MATRIX,
                perturbation_range=(-1.5, 0.5),
            )
        assert exc_info.value.code == SensitivityErrorCode.INVALID_PERTURBATION_RANGE

    def test_num_steps_too_low(self) -> None:
        with pytest.raises(SensitivityError) as exc_info:
            sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX, num_steps=3)
        assert exc_info.value.code == SensitivityErrorCode.INVALID_NUM_STEPS

    def test_num_steps_too_high(self) -> None:
        with pytest.raises(SensitivityError) as exc_info:
            sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX, num_steps=200)
        assert exc_info.value.code == SensitivityErrorCode.INVALID_NUM_STEPS

    def test_invalid_target_criterion(self) -> None:
        with pytest.raises(SensitivityError) as exc_info:
            sensitivity_ahp(
                ORACLE1_CRITERIA,
                ORACLE1_MATRIX,
                target_criteria=["NONEXISTENT"],
            )
        assert exc_info.value.code == SensitivityErrorCode.INVALID_TARGET_CRITERION

    def test_invalid_matrix(self) -> None:
        with pytest.raises(SensitivityError) as exc_info:
            sensitivity_ahp(
                ["A", "B"],
                [[1, 2], [3, 1]],  # not reciprocal
            )
        assert exc_info.value.code == SensitivityErrorCode.MATRIX_VALIDATION_FAILED


# ---------------------------------------------------------------------------
# TestOracleCases
# ---------------------------------------------------------------------------


class TestOracleCases:
    def test_oracle3_2x2_crossover(self) -> None:
        """Oracle 3: 2x2 exact formula, crossover at w_x = w_y = 0.5."""
        result = sensitivity_ahp(
            ORACLE3_CRITERIA,
            ORACLE3_MATRIX,
            perturbation_range=(-0.5, 0.5),
            num_steps=100,
        )
        # Baseline weights: [0.75, 0.25]
        assert abs(result.baseline_weights[0] - 0.75) < 1e-6
        assert abs(result.baseline_weights[1] - 0.25) < 1e-6

        cr_x = result.criterion_results[0]
        # Crossover should be detected
        assert len(cr_x.crossover_points) > 0
        # Crossover at delta = -0.25 (w_x goes from 0.75 to 0.5)
        crossover_found = any(abs(c - (-0.25)) < 0.02 for c in cr_x.crossover_points)
        assert crossover_found

    def test_oracle1_3x3_ranking_stable(self) -> None:
        """Oracle 1: 3x3 consistent, small perturbation keeps ranking."""
        result = sensitivity_ahp(
            ORACLE1_CRITERIA,
            ORACLE1_MATRIX,
            perturbation_range=(-0.1, 0.1),
            num_steps=10,
        )
        # All perturbed rankings should be [0, 1, 2] (stable)
        for cr in result.criterion_results:
            for ranking in cr.perturbed_rankings:
                assert ranking == [0, 1, 2]

    def test_oracle2_3x3_near_tie(self) -> None:
        """Oracle 2: 3x3 near-tie matrix."""
        result = sensitivity_ahp(
            ORACLE2_CRITERIA,
            ORACLE2_MATRIX,
            perturbation_range=(-0.1, 0.1),
            num_steps=20,
        )
        # Near-ties should be detected
        assert len(result.near_ties) > 0


# ---------------------------------------------------------------------------
# TestFullSweep
# ---------------------------------------------------------------------------


class TestFullSweep:
    def test_all_criteria_perturbed(self) -> None:
        result = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX, num_steps=10)
        assert len(result.criterion_results) == 3

    def test_target_criteria_subset(self) -> None:
        result = sensitivity_ahp(
            ORACLE1_CRITERIA,
            ORACLE1_MATRIX,
            target_criteria=["A"],
        )
        assert len(result.criterion_results) == 1
        assert result.criterion_results[0].criterion == "A"

    def test_output_dimensions(self) -> None:
        result = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX, num_steps=15)
        for cr in result.criterion_results:
            assert len(cr.perturbation_values) == 15
            assert len(cr.perturbed_weights) == 15
            assert len(cr.perturbed_rankings) == 15
            assert len(cr.consistency_flags) == 15
            assert len(cr.consistency_ratios) == 15
            for w in cr.perturbed_weights:
                assert len(w) == 3


# ---------------------------------------------------------------------------
# TestBounds
# ---------------------------------------------------------------------------


class TestBounds:
    def test_lower_bound(self) -> None:
        result = sensitivity_ahp(
            ORACLE1_CRITERIA,
            ORACLE1_MATRIX,
            perturbation_range=(-0.2, 0.3),
            num_steps=5,
        )
        cr_a = result.criterion_results[0]
        assert abs(cr_a.perturbation_values[0] - (-0.2)) < 1e-9

    def test_upper_bound(self) -> None:
        result = sensitivity_ahp(
            ORACLE1_CRITERIA,
            ORACLE1_MATRIX,
            perturbation_range=(-0.2, 0.3),
            num_steps=5,
        )
        cr_a = result.criterion_results[0]
        assert abs(cr_a.perturbation_values[-1] - 0.3) < 1e-9

    def test_step_count(self) -> None:
        result = sensitivity_ahp(
            ORACLE1_CRITERIA,
            ORACLE1_MATRIX,
            num_steps=7,
        )
        for cr in result.criterion_results:
            assert len(cr.perturbation_values) == 7


# ---------------------------------------------------------------------------
# TestErrorCodes
# ---------------------------------------------------------------------------


class TestErrorCodes:
    def test_all_error_codes_exist(self) -> None:
        codes = [
            SensitivityErrorCode.INVALID_INPUT,
            SensitivityErrorCode.INVALID_PERTURBATION_RANGE,
            SensitivityErrorCode.INVALID_NUM_STEPS,
            SensitivityErrorCode.INVALID_TARGET_CRITERION,
            SensitivityErrorCode.INVALID_METHOD,
            SensitivityErrorCode.MATRIX_VALIDATION_FAILED,
            SensitivityErrorCode.AHP_ENGINE_FAILED,
        ]
        assert len(codes) == 7

    def test_sensitivity_error_carries_code(self) -> None:
        err = SensitivityError(SensitivityErrorCode.INVALID_INPUT, "test")
        assert err.code == SensitivityErrorCode.INVALID_INPUT
        assert err.message == "test"
        assert "INVALID_INPUT" in str(err)


# ---------------------------------------------------------------------------
# TestSecurityRegression
# ---------------------------------------------------------------------------


class TestSecurityRegression:
    def test_no_qgis_imports(self) -> None:
        import lunar_gis.analysis.sensitivity as mod

        source = open(mod.__file__).read()  # noqa: SIM115
        assert "from qgis" not in source
        assert "import qgis" not in source

    def test_no_network_imports(self) -> None:
        import lunar_gis.analysis.sensitivity as mod

        source = open(mod.__file__).read()  # noqa: SIM115
        assert "import requests" not in source
        assert "import urllib" not in source
        assert "import http" not in source

    def test_no_numpy_scipy(self) -> None:
        import lunar_gis.analysis.sensitivity as mod

        source = open(mod.__file__).read()  # noqa: SIM115
        assert "import numpy" not in source
        assert "import scipy" not in source

    def test_no_exec_eval(self) -> None:
        import lunar_gis.analysis.sensitivity as mod

        source = open(mod.__file__).read()  # noqa: SIM115
        assert "eval(" not in source
        assert "exec(" not in source

    def test_no_subprocess(self) -> None:
        import lunar_gis.analysis.sensitivity as mod

        source = open(mod.__file__).read()  # noqa: SIM115
        assert "import subprocess" not in source

    def test_no_pickle(self) -> None:
        import lunar_gis.analysis.sensitivity as mod

        source = open(mod.__file__).read()  # noqa: SIM115
        assert "import pickle" not in source


# ---------------------------------------------------------------------------
# TestImmutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_input_criteria_not_mutated(self) -> None:
        criteria = list(ORACLE1_CRITERIA)
        original = list(criteria)
        sensitivity_ahp(criteria, ORACLE1_MATRIX)
        assert criteria == original

    def test_input_matrix_not_mutated(self) -> None:
        matrix = [list(row) for row in ORACLE1_MATRIX]
        original = [list(row) for row in matrix]
        sensitivity_ahp(ORACLE1_CRITERIA, matrix)
        assert matrix == original

    def test_baseline_not_mutated_by_scenarios(self) -> None:
        result = sensitivity_ahp(
            ORACLE1_CRITERIA,
            ORACLE1_MATRIX,
            perturbation_range=(-0.5, 0.5),
        )
        # Run again, check baseline unchanged
        result2 = sensitivity_ahp(ORACLE1_CRITERIA, ORACLE1_MATRIX)
        assert result.baseline_weights == result2.baseline_weights
