"""Deterministic AHP core engine.

Pure stdlib, no QGIS/LLM/network/filesystem. Implements the
methodology frozen in docs/research/M2-AHP-METHODOLOGY-AND-OSS-AUDIT.md.

Public API (functions):
  - ahp(criteria, matrix) -> AHPResult
  - validate_ahp_input(criteria, matrix) -> None (raises AHPError)

Public types (frozen dataclasses / enums):
  - AHPResult          -- weights + consistency + math provenance
  - ConsistencyReport  -- lambda_max, ci, ri, cr, flag, trivial_consistency
  - ConsistencyFlag    -- ACCEPTABLE | ACCEPTABLE_WITH_WARNING | REVISE_REQUIRED
  - AHPError           -- exception with stable AHPErrorCode
  - AHPErrorCode       -- 11 codes (9 validation + 2 numerical)

Error taxonomy (deterministic, first failure wins):
  Validation: shape -> size -> criteria -> diagonal -> numeric -> scale -> reciprocity
  Numerical:  NUMERICAL_CONVERGENCE_FAILURE, NUMERICAL_RESULT_VALIDATION_FAILURE

Consistency classification (n >= 3, with FLOAT_COMPARE_EPS = 1e-9):
  ACCEPTABLE              -- CR <= 0.10 + eps
  ACCEPTABLE_WITH_WARNING -- 0.10 + eps < CR <= 0.20 + eps
  REVISE_REQUIRED         -- CR > 0.20 + eps
  n < 3: always ACCEPTABLE with trivial_consistency = true

Deterministic guarantees (M2-AHP §11):
  Same input -> byte-identical output; no RNG; no timestamps in math results.

Provenance fields (M2-AHP §12): method, engine_version, numerical_policy_version,
  display_precision, input_hash (SHA-256), iteration_count.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

try:
    from lunar_gis.__version__ import __version__ as _ENGINE_VERSION
except Exception:
    _ENGINE_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Constants (frozen per M2-T01)
# ---------------------------------------------------------------------------

SAATY_SCALE: tuple[float, ...] = (
    1.0,
    2.0,
    3.0,
    4.0,
    5.0,
    6.0,
    7.0,
    8.0,
    9.0,
    1.0 / 2.0,
    1.0 / 3.0,
    1.0 / 4.0,
    1.0 / 5.0,
    1.0 / 6.0,
    1.0 / 7.0,
    1.0 / 8.0,
    1.0 / 9.0,
)

SAATY_RI_1980: dict[int, float] = {
    1: 0.00,
    2: 0.00,
    3: 0.58,
    4: 0.90,
    5: 1.12,
    6: 1.24,
    7: 1.32,
    8: 1.41,
    9: 1.45,
    10: 1.49,
}

RI_SOURCE = "saaty-1980"
CR_ACCEPT = 0.10
CR_TOLERATE = 0.20
FLOAT_COMPARE_EPS = 1e-9
POWER_TOL = 1e-12
POWER_MAX_ITER = 10000
RECIPROCITY_TOL = 1e-9
SCALE_MEMBERSHIP_TOL = 1e-12
MAX_N = 10
MIN_N = 1
NUMERICAL_POLICY_VERSION = "1.0"
METHOD_ID = "principal-right-eigenvector/power-iteration"
DISPLAY_PRECISION = 6
RESIDUAL_TOL = 1e-9


# ---------------------------------------------------------------------------
# Error taxonomy
# ---------------------------------------------------------------------------


class AHPErrorCode(str, Enum):
    NON_SQUARE_MATRIX = "NON_SQUARE_MATRIX"
    UNSUPPORTED_MATRIX_SIZE = "UNSUPPORTED_MATRIX_SIZE"
    INVALID_DIAGONAL = "INVALID_DIAGONAL"
    INVALID_NUMERIC_VALUE = "INVALID_NUMERIC_VALUE"
    OFF_SCALE_VALUE = "OFF_SCALE_VALUE"
    RECIPROCITY_VIOLATION = "RECIPROCITY_VIOLATION"
    INCOMPLETE_MATRIX = "INCOMPLETE_MATRIX"
    DUPLICATE_CRITERION = "DUPLICATE_CRITERION"
    EMPTY_CRITERION_NAME = "EMPTY_CRITERION_NAME"
    NUMERICAL_CONVERGENCE_FAILURE = "NUMERICAL_CONVERGENCE_FAILURE"
    NUMERICAL_RESULT_VALIDATION_FAILURE = "NUMERICAL_RESULT_VALIDATION_FAILURE"


class AHPError(ValueError):
    """Deterministic AHP validation/numerical error with a stable code."""

    def __init__(self, code: AHPErrorCode | str, message: str) -> None:
        if isinstance(code, str):
            code = AHPErrorCode(code)
        self.code = code
        super().__init__(f"[{code.value}] {message}")


# ---------------------------------------------------------------------------
# Consistency flag
# ---------------------------------------------------------------------------


class ConsistencyFlag(str, Enum):
    ACCEPTABLE = "ACCEPTABLE"
    ACCEPTABLE_WITH_WARNING = "ACCEPTABLE_WITH_WARNING"
    REVISE_REQUIRED = "REVISE_REQUIRED"


# ---------------------------------------------------------------------------
# Result types (immutable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConsistencyReport:
    lambda_max: float
    ci: float
    ri_source: str
    ri_value: float
    cr: float
    flag: ConsistencyFlag
    trivial_consistency: bool


@dataclass(frozen=True)
class AHPResult:
    criteria: tuple[str, ...]
    matrix: tuple[tuple[float, ...], ...]
    weights: tuple[float, ...]
    consistency: ConsistencyReport
    method: str
    engine_version: str
    numerical_policy_version: str
    display_precision: int
    input_hash: str
    iteration_count: int

    def weights_dict(self) -> dict[str, float]:
        return dict(zip(self.criteria, self.weights, strict=True))

    def to_dict(self) -> dict[str, object]:
        return {
            "criteria": list(self.criteria),
            "matrix": [list(row) for row in self.matrix],
            "weights": list(self.weights),
            "weights_dict": self.weights_dict(),
            "lambda_max": self.consistency.lambda_max,
            "ci": self.consistency.ci,
            "ri_source": self.consistency.ri_source,
            "ri_value": self.consistency.ri_value,
            "cr": self.consistency.cr,
            "flag": self.consistency.flag.value,
            "trivial_consistency": self.consistency.trivial_consistency,
            "method": self.method,
            "engine_version": self.engine_version,
            "numerical_policy_version": self.numerical_policy_version,
            "display_precision": self.display_precision,
            "input_hash": self.input_hash,
            "iteration_count": self.iteration_count,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_finite_positive_number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    fv = float(value)
    if not math.isfinite(fv):
        return False
    return fv > 0


def _is_scale_value(value: float) -> bool:
    for s in SAATY_SCALE:
        if math.isclose(value, s, rel_tol=SCALE_MEMBERSHIP_TOL, abs_tol=0.0):
            return True
    return False


def _matvec(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> list[float]:
    n = len(matrix)
    result: list[float] = []
    for i in range(n):
        row = matrix[i]
        acc = 0.0
        for j in range(n):
            acc += float(row[j]) * float(vector[j])
        result.append(acc)
    return result


def _canonical_input_hash(criteria: Sequence[str], matrix: Sequence[Sequence[float]]) -> str:
    payload = {
        "criteria": list(criteria),
        "matrix": [list(map(float, row)) for row in matrix],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Validation (deterministic order, first failure wins)
# ---------------------------------------------------------------------------


def validate_ahp_input(
    criteria: object,
    matrix: object,
) -> None:
    """Validate (criteria, matrix) per §9 order. Raises AHPError on first failure."""
    # Shape: matrix must be list/tuple of list/tuple, non-empty, square
    if not isinstance(matrix, (list, tuple)):
        raise AHPError(AHPErrorCode.NON_SQUARE_MATRIX, "matrix must be a list/tuple of rows")
    n = len(matrix)
    if n == 0:
        raise AHPError(AHPErrorCode.NON_SQUARE_MATRIX, "matrix must be non-empty")
    for idx, row in enumerate(matrix):
        if row is None:
            raise AHPError(AHPErrorCode.NON_SQUARE_MATRIX, f"row {idx} is None (non-square)")
        if not isinstance(row, (list, tuple)):
            raise AHPError(AHPErrorCode.NON_SQUARE_MATRIX, f"row {idx} must be a list/tuple")
        if len(row) != n:
            raise AHPError(
                AHPErrorCode.NON_SQUARE_MATRIX,
                f"matrix must be square: row {idx} has length {len(row)} != {n}",
            )
        for col_idx, val in enumerate(row):
            if val is None:
                raise AHPError(
                    AHPErrorCode.INCOMPLETE_MATRIX,
                    f"matrix[{idx}][{col_idx}] is None (missing entry)",
                )

    # Size: 1..10
    if n < MIN_N or n > MAX_N:
        raise AHPError(
            AHPErrorCode.UNSUPPORTED_MATRIX_SIZE,
            f"matrix size n={n} not in supported range [{MIN_N}..{MAX_N}]",
        )

    # Criteria: must be sequence of non-empty unique strings, length n
    if not isinstance(criteria, (list, tuple)):
        raise AHPError(AHPErrorCode.EMPTY_CRITERION_NAME, "criteria must be a list/tuple of strings")
    crit = list(criteria)
    if len(crit) != n:
        raise AHPError(
            AHPErrorCode.NON_SQUARE_MATRIX,
            f"criteria length {len(crit)} != matrix size {n}",
        )
    seen: set[str] = set()
    for idx, name in enumerate(crit):
        if not isinstance(name, str):
            raise AHPError(
                AHPErrorCode.EMPTY_CRITERION_NAME,
                f"criteria[{idx}] must be a string, got {type(name).__name__}",
            )
        if name.strip() == "":
            raise AHPError(AHPErrorCode.EMPTY_CRITERION_NAME, f"criteria[{idx}] is empty or whitespace-only")
        if name in seen:
            raise AHPError(AHPErrorCode.DUPLICATE_CRITERION, f"duplicate criterion {name!r}")
        seen.add(name)

    # Diagonal: exact ==1.0
    for i in range(n):
        diag = matrix[i][i]  # type: ignore[index]
        if diag != 1 and diag != 1.0:  # type: ignore[comparison-overlap]
            raise AHPError(AHPErrorCode.INVALID_DIAGONAL, f"diagonal [{i}][{i}] must be 1, got {diag!r}")

    # Numeric finiteness/positivity (before scale, per boundary disambiguation)
    for i in range(n):
        for j in range(n):
            val = matrix[i][j]  # type: ignore[index]
            if isinstance(val, bool):
                raise AHPError(
                    AHPErrorCode.INVALID_NUMERIC_VALUE,
                    f"matrix[{i}][{j}] is bool (not a valid judgment)",
                )
            if not isinstance(val, (int, float)):
                raise AHPError(
                    AHPErrorCode.INVALID_NUMERIC_VALUE,
                    f"matrix[{i}][{j}] must be a number, got {type(val).__name__}",
                )
            fv = float(val)
            if not math.isfinite(fv):
                raise AHPError(
                    AHPErrorCode.INVALID_NUMERIC_VALUE,
                    f"matrix[{i}][{j}] must be finite, got {val!r}",
                )
            if fv <= 0:
                raise AHPError(
                    AHPErrorCode.INVALID_NUMERIC_VALUE,
                    f"matrix[{i}][{j}] must be strictly positive, got {val!r}",
                )

    # Scale membership (nearest match within 1e-12 relative)
    for i in range(n):
        for j in range(n):
            fv = float(matrix[i][j])  # type: ignore[index]
            if not _is_scale_value(fv):
                raise AHPError(
                    AHPErrorCode.OFF_SCALE_VALUE,
                    f"matrix[{i}][{j}]={fv!r} not in Saaty 1..9 scale (17 values) within {SCALE_MEMBERSHIP_TOL}",
                )

    # Reciprocity
    for i in range(n):
        for j in range(i + 1, n):
            a = float(matrix[i][j])  # type: ignore[index]
            b = float(matrix[j][i])  # type: ignore[index]
            if abs(a * b - 1.0) > RECIPROCITY_TOL:
                raise AHPError(
                    AHPErrorCode.RECIPROCITY_VIOLATION,
                    f"reciprocity violation at [{i}][{j}]={a!r} * [{j}][{i}]={b!r} "
                    f"= {a * b!r} != 1 within {RECIPROCITY_TOL}",
                )


# ---------------------------------------------------------------------------
# Priority vector (power iteration) + consistency
# ---------------------------------------------------------------------------


def _priority_vector_and_iterations(
    matrix: tuple[tuple[float, ...], ...],
) -> tuple[tuple[float, ...], int]:
    n = len(matrix)
    if n == 1:
        return ((1.0,), 0)
    if n == 2:
        a = float(matrix[0][1])
        # Exact per spec §4: avoids iterative error for 2x2
        w0 = a / (1.0 + a)
        w1 = 1.0 / (1.0 + a)
        vec = (w0, w1)
        # Validate positivity/sum as with iterative path
        if not (math.isfinite(w0) and math.isfinite(w1) and w0 > 0 and w1 > 0):
            raise AHPError(
                AHPErrorCode.NUMERICAL_RESULT_VALIDATION_FAILURE,
                "2x2 exact weights not positive/finite",
            )
        return (vec, 0)

    # Power iteration for n >=3
    v: list[float] = [1.0 / n] * n
    for iteration in range(1, POWER_MAX_ITER + 1):
        w = _matvec(matrix, v)
        s = sum(w)
        if not math.isfinite(s) or s == 0:
            raise AHPError(
                AHPErrorCode.NUMERICAL_RESULT_VALIDATION_FAILURE,
                "power iteration: normalization sum not finite/positive",
            )
        v_new = [x / s for x in w]
        # Convergence: max component change
        delta = max(abs(a - b) for a, b in zip(v_new, v, strict=True))
        v = v_new
        if delta < POWER_TOL:
            # Positivity
            for idx, val in enumerate(v):
                if not math.isfinite(val) or val <= 0:
                    raise AHPError(
                        AHPErrorCode.NUMERICAL_RESULT_VALIDATION_FAILURE,
                        f"weight[{idx}] not positive/finite after convergence: {val!r}",
                    )
            # Sum check
            total = sum(v)
            if abs(total - 1.0) > 1e-9:
                raise AHPError(
                    AHPErrorCode.NUMERICAL_RESULT_VALIDATION_FAILURE,
                    f"weights sum {total!r} not 1 within 1e-9",
                )
            # Residual: ||Aw - lam*w||_inf < 1e-9
            aw = _matvec(matrix, v)
            # lam per spec: mean((Aw)_i / w_i) — but need lam for residual
            # Compute mean lam first
            lam_candidates = []
            for i in range(n):
                if v[i] <= 0 or not math.isfinite(v[i]):
                    raise AHPError(
                        AHPErrorCode.NUMERICAL_RESULT_VALIDATION_FAILURE,
                        f"weight[{i}] not positive/finite for lambda calc",
                    )
                lam_candidates.append(aw[i] / v[i])
            lam = sum(lam_candidates) / n
            resid = max(abs(aw[i] - lam * v[i]) for i in range(n))
            if resid >= RESIDUAL_TOL:
                raise AHPError(
                    AHPErrorCode.NUMERICAL_RESULT_VALIDATION_FAILURE,
                    f"eigen residual {resid!r} >= {RESIDUAL_TOL}",
                )
            return (tuple(v), iteration)

    raise AHPError(
        AHPErrorCode.NUMERICAL_CONVERGENCE_FAILURE,
        f"power iteration did not converge within {POWER_MAX_ITER} iterations (tol {POWER_TOL})",
    )


def _classify_consistency(n: int, cr: float) -> ConsistencyFlag:
    if n < 3:
        return ConsistencyFlag.ACCEPTABLE
    if cr <= CR_ACCEPT + FLOAT_COMPARE_EPS:
        return ConsistencyFlag.ACCEPTABLE
    if cr <= CR_TOLERATE + FLOAT_COMPARE_EPS:
        return ConsistencyFlag.ACCEPTABLE_WITH_WARNING
    return ConsistencyFlag.REVISE_REQUIRED


def ahp(
    criteria: Sequence[str],
    matrix: Sequence[Sequence[float | int]],
) -> AHPResult:
    """Compute AHP weights + consistency for one pairwise matrix.

    Validates per §9 order, computes principal eigenvector per §5/§8,
    then CI/CR/flag per §6/§7. Deterministic, stdlib-only, no QGIS/LLM.
    Raises AHPError with a stable code on invalid input or numerical failure.
    """
    # Validate (deterministic, first failure wins)
    validate_ahp_input(criteria, matrix)

    n = len(criteria)  # type: ignore[arg-type]
    # Canonical immutable copies
    crit_t = tuple(str(c) for c in criteria)  # type: ignore[arg-type]
    mat_t: tuple[tuple[float, ...], ...] = tuple(
        tuple(float(v) for v in row)  # type: ignore[arg-type]
        for row in matrix  # type: ignore[arg-type]
    )

    # Priority vector
    weights, iteration_count = _priority_vector_and_iterations(mat_t)

    # Lambda_max, CI, RI, CR
    if n == 1:
        lambda_max = 1.0
        ci = 0.0
        ri_value = SAATY_RI_1980[1]
        cr = 0.0
        trivial = True
    elif n == 2:
        lambda_max = 2.0
        ci = 0.0
        ri_value = SAATY_RI_1980[2]
        cr = 0.0
        trivial = True
    else:
        aw = _matvec(mat_t, list(weights))
        lam_candidates = [aw[i] / weights[i] for i in range(n)]
        lambda_max = sum(lam_candidates) / n
        if not math.isfinite(lambda_max):
            raise AHPError(
                AHPErrorCode.NUMERICAL_RESULT_VALIDATION_FAILURE,
                "lambda_max not finite",
            )
        # Residual already checked in iteration path, but re-check for n>=3
        resid = max(abs(aw[i] - lambda_max * weights[i]) for i in range(n))
        if resid >= RESIDUAL_TOL:
            raise AHPError(
                AHPErrorCode.NUMERICAL_RESULT_VALIDATION_FAILURE,
                f"lambda residual {resid!r} >= {RESIDUAL_TOL}",
            )
        ci = (lambda_max - n) / (n - 1)
        if not math.isfinite(ci):
            raise AHPError(AHPErrorCode.NUMERICAL_RESULT_VALIDATION_FAILURE, "CI not finite")
        ri_value = SAATY_RI_1980[n]
        cr = ci / ri_value if ri_value != 0 else 0.0
        if not math.isfinite(cr):
            raise AHPError(AHPErrorCode.NUMERICAL_RESULT_VALIDATION_FAILURE, "CR not finite")
        trivial = False

    flag = _classify_consistency(n, cr)

    input_hash = _canonical_input_hash(crit_t, mat_t)

    consistency = ConsistencyReport(
        lambda_max=lambda_max,
        ci=ci,
        ri_source=RI_SOURCE,
        ri_value=ri_value,
        cr=cr,
        flag=flag,
        trivial_consistency=trivial,
    )

    return AHPResult(
        criteria=crit_t,
        matrix=mat_t,
        weights=weights,
        consistency=consistency,
        method=METHOD_ID,
        engine_version=_ENGINE_VERSION,
        numerical_policy_version=NUMERICAL_POLICY_VERSION,
        display_precision=DISPLAY_PRECISION,
        input_hash=input_hash,
        iteration_count=iteration_count,
    )
