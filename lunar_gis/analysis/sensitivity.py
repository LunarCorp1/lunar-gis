"""Deterministic AHP sensitivity analysis engine.

Pure stdlib, no QGIS/LLM/network/filesystem. Implements OAT weight
perturbation as defined in docs/research/M2-SENSITIVITY-ANALYSIS-DESIGN.md.

Public API:
  - sensitivity_ahp(criteria, matrix, ...) -> SensitivityResult
  - SensitivityMethod         -- OAT_WEIGHT
  - SensitivityResult         -- full result with provenance
  - CriterionSensitivity      -- per-criterion perturbation results
  - SensitivityError          -- domain-specific exception
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from lunar_gis.analysis.ahp import (
    AHPError,
    FLOAT_COMPARE_EPS,
    ahp,
)

# ---------------------------------------------------------------------------
# Constants (frozen per M2-T05)
# ---------------------------------------------------------------------------

NEAR_TIE_TOL = 1e-6
SENSITIVITY_POLICY_VERSION = "1.0"
RANKING_POLICY_VERSION = "1.0"
CONSISTENCY_POLICY_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Error taxonomy
# ---------------------------------------------------------------------------


class SensitivityErrorCode(str, Enum):
    """Stable error codes for sensitivity analysis failures."""

    INVALID_INPUT = "INVALID_INPUT"
    INVALID_PERTURBATION_RANGE = "INVALID_PERTURBATION_RANGE"
    INVALID_NUM_STEPS = "INVALID_NUM_STEPS"
    INVALID_TARGET_CRITERION = "INVALID_TARGET_CRITERION"
    INVALID_METHOD = "INVALID_METHOD"
    MATRIX_VALIDATION_FAILED = "MATRIX_VALIDATION_FAILED"
    AHP_ENGINE_FAILED = "AHP_ENGINE_FAILED"


class SensitivityError(Exception):
    """Domain-specific exception for sensitivity analysis failures.

    Attributes:
        code: Stable SensitivityErrorCode for programmatic handling.
        message: Human-readable error description.
    """

    def __init__(self, code: SensitivityErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code.value}] {message}")


# ---------------------------------------------------------------------------
# Methods
# ---------------------------------------------------------------------------


class SensitivityMethod(str, Enum):
    """Sensitivity analysis method.

    Only OAT_WEIGHT is implemented. OAT_PAIRWISE is defined for future use
    but raises SensitivityError if requested.
    """

    OAT_WEIGHT = "OAT_WEIGHT"
    OAT_PAIRWISE = "OAT_PAIRWISE"


# ---------------------------------------------------------------------------
# Result types (immutable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CriterionSensitivity:
    """Sensitivity result for a single criterion."""

    criterion: str
    baseline_weight: float
    stability_lower: float
    stability_upper: float
    crossover_points: list[float]
    perturbation_values: list[float]
    perturbed_weights: list[list[float]]
    perturbed_rankings: list[list[int]]
    consistency_flags: list[str]
    consistency_ratios: list[float]


@dataclass(frozen=True)
class SensitivityResult:
    """Complete sensitivity analysis result."""

    criteria: list[str]
    baseline_weights: list[float]
    baseline_ranking: list[int]
    criterion_results: list[CriterionSensitivity]
    method: SensitivityMethod
    sensitivity_policy_version: str
    numerical_policy_version: str
    engine_version: str
    input_hash: str
    perturbation_range: tuple[float, float]
    num_steps: int
    target_criteria: list[str] | None
    ranking_policy_version: str
    consistency_policy_version: str
    near_ties: list[tuple[str, str]]


# ---------------------------------------------------------------------------
# Ranking policy
# ---------------------------------------------------------------------------


def _compute_ranking(weights: Sequence[float]) -> list[int]:
    """Compute ranking from weights.

    Rank 0 = highest weight. Tied weights receive the same rank.
    No artificial tie-breaking.
    """
    n = len(weights)
    ranking = [0] * n
    for i in range(n):
        rank = 0
        for j in range(n):
            if j == i:
                continue
            if weights[j] > weights[i] + FLOAT_COMPARE_EPS:
                rank += 1
        ranking[i] = rank
    return ranking


def _detect_near_ties(
    criteria: Sequence[str], weights: Sequence[float]
) -> list[tuple[str, str]]:
    """Detect near-tied criteria pairs."""
    n = len(criteria)
    near_ties: list[tuple[str, str]] = []
    for i in range(n):
        for j in range(i + 1, n):
            if abs(weights[i] - weights[j]) < NEAR_TIE_TOL:
                near_ties.append((criteria[i], criteria[j]))
    return near_ties


def _rankings_equal(r1: list[int], r2: list[int]) -> bool:
    """Check if two rankings are identical."""
    return len(r1) == len(r2) and all(a == b for a, b in zip(r1, r2, strict=True))


# ---------------------------------------------------------------------------
# OAT weight perturbation
# ---------------------------------------------------------------------------


def _perturb_weights_oat(
    baseline_weights: list[float],
    target_idx: int,
    delta: float,
) -> list[float]:
    """Perturb a single criterion weight by delta.

    Uses the OAT formula from M2-T05 §7.1:
      w'_k = w_k + delta
      w'_i = w_i * (1 - w'_k) / (1 - w_k)  for i != k
      Normalize: w' = w' / sum(w')

    The ε guard in the sweep range prevents division by zero.
    """
    n = len(baseline_weights)
    w_k = baseline_weights[target_idx]
    w_new_k = w_k + delta

    perturbed = [0.0] * n
    perturbed[target_idx] = w_new_k

    denom = 1.0 - w_k
    for i in range(n):
        if i == target_idx:
            continue
        perturbed[i] = baseline_weights[i] * (1.0 - w_new_k) / denom

    # Normalize (floating-point hygiene)
    total = sum(perturbed)
    if total > 0:
        perturbed = [w / total for w in perturbed]

    return perturbed


def _clamp_perturbation_range(
    baseline_weights: list[float],
    target_idx: int,
    perturbation_range: tuple[float, float],
) -> tuple[float, float]:
    """Clamp perturbation range to prevent negative weights.

    For criterion k with weight w_k, the valid delta range is:
      [-w_k + ε, 1 - w_k - ε]
    """
    w_k = baseline_weights[target_idx]
    eps = FLOAT_COMPARE_EPS
    valid_min = -w_k + eps
    valid_max = 1.0 - w_k - eps
    clamped_min = max(perturbation_range[0], valid_min)
    clamped_max = min(perturbation_range[1], valid_max)
    return (clamped_min, clamped_max)


def _compute_stability_interval(
    baseline_ranking: list[int],
    perturbation_values: list[float],
    perturbed_rankings: list[list[int]],
) -> tuple[float, float]:
    """Compute the global stability interval for a criterion.

    The stability interval is the range of delta where the entire ranking
    remains unchanged from the baseline.

    Uses conservative estimation: if an unstable point is found, the interval
    boundary is set to the midpoint between the last stable and first unstable
    point. If no unstable point is found on a side, the full range is retained.
    """
    step_size = perturbation_values[1] - perturbation_values[0] if len(perturbation_values) > 1 else 0.0

    # Default: full range (no instability found)
    stable_lower = perturbation_values[0]
    stable_upper = perturbation_values[-1]

    # Find lower bound: scan forward through non-positive deltas.
    # Only overwrite when an unstable point is found (midpoint estimation).
    for i, delta in enumerate(perturbation_values):
        if delta > 0:
            break
        if not _rankings_equal(perturbed_rankings[i], baseline_ranking):
            # First unstable point below baseline
            if i > 0:
                stable_lower = (perturbation_values[i - 1] + delta) / 2.0
            else:
                stable_lower = delta + step_size
            break
    # If no break, stable_lower stays at perturbation_values[0] (full range)

    # Find upper bound: scan backward through non-negative deltas.
    # Only overwrite when an unstable point is found (midpoint estimation).
    for i in range(len(perturbation_values) - 1, -1, -1):
        delta = perturbation_values[i]
        if delta < 0:
            break
        if not _rankings_equal(perturbed_rankings[i], baseline_ranking):
            # First unstable point above baseline
            if i < len(perturbation_values) - 1:
                stable_upper = (perturbation_values[i + 1] + delta) / 2.0
            else:
                stable_upper = delta - step_size
            break
    # If no break, stable_upper stays at perturbation_values[-1] (full range)

    return (stable_lower, stable_upper)


def _detect_crossovers(
    perturbation_values: list[float],
    perturbed_rankings: list[list[int]],
    baseline_ranking: list[int],
) -> list[float]:
    """Detect crossover points where ranking changes from baseline.

    Returns the perturbation values at which the ranking first differs.
    """
    crossovers: list[float] = []
    for i, delta in enumerate(perturbation_values):
        if not _rankings_equal(perturbed_rankings[i], baseline_ranking):
            crossovers.append(delta)
    return crossovers


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_sensitivity_input(
    criteria: Sequence[str],
    matrix: Sequence[Sequence[float]],
    method: SensitivityMethod,
    perturbation_range: tuple[float, float],
    num_steps: int,
    target_criteria: Sequence[str] | None,
) -> None:
    """Validate sensitivity input parameters."""
    if not criteria:
        raise SensitivityError(
            SensitivityErrorCode.INVALID_INPUT,
            "criteria must be non-empty",
        )

    if len(criteria) < 2:
        raise SensitivityError(
            SensitivityErrorCode.INVALID_INPUT,
            "sensitivity analysis requires at least 2 criteria",
        )

    if len(criteria) > 10:
        raise SensitivityError(
            SensitivityErrorCode.INVALID_INPUT,
            f"criteria count {len(criteria)} exceeds MAX_N (10)",
        )

    if method == SensitivityMethod.OAT_PAIRWISE:
        raise SensitivityError(
            SensitivityErrorCode.INVALID_METHOD,
            "OAT_PAIRWISE is not yet implemented; use OAT_WEIGHT",
        )

    if method != SensitivityMethod.OAT_WEIGHT:
        raise SensitivityError(
            SensitivityErrorCode.INVALID_METHOD,
            f"unsupported method: {method!r}",
        )

    min_delta, max_delta = perturbation_range
    if not (-1.0 < min_delta < 1.0):
        raise SensitivityError(
            SensitivityErrorCode.INVALID_PERTURBATION_RANGE,
            f"min_delta must be in (-1.0, 1.0), got {min_delta}",
        )
    if not (-1.0 < max_delta < 1.0):
        raise SensitivityError(
            SensitivityErrorCode.INVALID_PERTURBATION_RANGE,
            f"max_delta must be in (-1.0, 1.0), got {max_delta}",
        )
    if min_delta >= max_delta:
        raise SensitivityError(
            SensitivityErrorCode.INVALID_PERTURBATION_RANGE,
            f"min_delta ({min_delta}) must be < max_delta ({max_delta})",
        )

    if num_steps < 5 or num_steps > 100:
        raise SensitivityError(
            SensitivityErrorCode.INVALID_NUM_STEPS,
            f"num_steps must be in [5, 100], got {num_steps}",
        )

    if target_criteria is not None:
        criteria_set = set(criteria)
        for tc in target_criteria:
            if tc not in criteria_set:
                raise SensitivityError(
                    SensitivityErrorCode.INVALID_TARGET_CRITERION,
                    f"target criterion {tc!r} not in criteria",
                )

    # Validate matrix via AHP engine
    try:
        ahp(list(criteria), [list(row) for row in matrix])
    except AHPError as e:
        raise SensitivityError(
            SensitivityErrorCode.MATRIX_VALIDATION_FAILED,
            f"AHP validation failed: {e}",
        ) from e


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------


def sensitivity_ahp(
    criteria: Sequence[str],
    matrix: Sequence[Sequence[float]],
    method: str | SensitivityMethod = "OAT_WEIGHT",
    perturbation_range: tuple[float, float] = (-0.3, 0.3),
    num_steps: int = 20,
    target_criteria: Sequence[str] | None = None,
) -> SensitivityResult:
    """Run deterministic AHP sensitivity analysis.

    Args:
        criteria: n criterion names.
        matrix: n×n reciprocal pairwise comparison matrix.
        method: Sensitivity method ("OAT_WEIGHT" only; "OAT_PAIRWISE" raises error).
        perturbation_range: (min_delta, max_delta) absolute weight offsets.
        num_steps: Number of sweep steps (5–100).
        target_criteria: Subset of criteria to analyze (None = all).

    Returns:
        SensitivityResult with full perturbation analysis and provenance.

    Raises:
        SensitivityError: On invalid input or AHP engine failure.
    """
    # Coerce method
    if isinstance(method, str):
        try:
            method_enum = SensitivityMethod(method)
        except ValueError:
            raise SensitivityError(
                SensitivityErrorCode.INVALID_METHOD,
                f"unsupported method: {method!r}",
            ) from None
    else:
        method_enum = method

    # Validate
    _validate_sensitivity_input(
        criteria, matrix, method_enum, perturbation_range, num_steps, target_criteria
    )

    # Compute baseline
    criteria_list = list(criteria)
    matrix_list = [list(row) for row in matrix]

    try:
        baseline = ahp(criteria_list, matrix_list)
    except AHPError as e:
        raise SensitivityError(
            SensitivityErrorCode.AHP_ENGINE_FAILED,
            f"AHP engine failed: {e}",
        ) from e

    baseline_weights = list(baseline.weights)
    baseline_ranking = _compute_ranking(baseline_weights)
    near_ties = _detect_near_ties(criteria_list, baseline_weights)

    # Determine target indices
    if target_criteria is not None:
        target_indices = [criteria_list.index(tc) for tc in target_criteria]
    else:
        target_indices = list(range(len(criteria_list)))

    # Generate perturbation sequence
    min_delta, max_delta = perturbation_range
    step_size = (max_delta - min_delta) / (num_steps - 1)
    perturbation_values = [min_delta + i * step_size for i in range(num_steps)]

    # Run OAT weight perturbation for each target criterion
    criterion_results: list[CriterionSensitivity] = []

    for target_idx in target_indices:
        target_name = criteria_list[target_idx]
        w_k = baseline_weights[target_idx]

        # Clamp perturbation range for this criterion
        clamped_min, clamped_max = _clamp_perturbation_range(
            baseline_weights, target_idx, perturbation_range
        )
        clamped_step_size = (clamped_max - clamped_min) / (num_steps - 1)
        clamped_values = [clamped_min + i * clamped_step_size for i in range(num_steps)]

        perturbed_weights_list: list[list[float]] = []
        perturbed_rankings_list: list[list[int]] = []
        consistency_flags_list: list[str] = []
        consistency_ratios_list: list[float] = []

        for delta in clamped_values:
            perturbed_w = _perturb_weights_oat(baseline_weights, target_idx, delta)
            perturbed_weights_list.append(perturbed_w)
            perturbed_rankings_list.append(_compute_ranking(perturbed_w))
            consistency_flags_list.append(baseline.consistency.flag.value)
            consistency_ratios_list.append(baseline.consistency.cr)

        # Stability interval
        stability_lower, stability_upper = _compute_stability_interval(
            baseline_ranking, clamped_values, perturbed_rankings_list,
        )

        # Crossover detection
        crossovers = _detect_crossovers(
            clamped_values, perturbed_rankings_list, baseline_ranking
        )

        criterion_results.append(
            CriterionSensitivity(
                criterion=target_name,
                baseline_weight=w_k,
                stability_lower=stability_lower,
                stability_upper=stability_upper,
                crossover_points=crossovers,
                perturbation_values=clamped_values,
                perturbed_weights=perturbed_weights_list,
                perturbed_rankings=perturbed_rankings_list,
                consistency_flags=consistency_flags_list,
                consistency_ratios=consistency_ratios_list,
            )
        )

    return SensitivityResult(
        criteria=criteria_list,
        baseline_weights=baseline_weights,
        baseline_ranking=baseline_ranking,
        criterion_results=criterion_results,
        method=method_enum,
        sensitivity_policy_version=SENSITIVITY_POLICY_VERSION,
        numerical_policy_version=baseline.numerical_policy_version,
        engine_version=baseline.engine_version,
        input_hash=baseline.input_hash,
        perturbation_range=perturbation_range,
        num_steps=num_steps,
        target_criteria=list(target_criteria) if target_criteria is not None else None,
        ranking_policy_version=RANKING_POLICY_VERSION,
        consistency_policy_version=CONSISTENCY_POLICY_VERSION,
        near_ties=near_ties,
    )
