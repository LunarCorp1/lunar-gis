# M2-T05: AHP Sensitivity Analysis — Methodology & Design Audit

- Status: Proposed
- Date: 2026-09-15
- Author: Lunar GIS maintainers
- Milestone: M2 (AHP) — design only, no implementation
- Related: AGENTS.md:1–12, M2-AHP-METHODOLOGY-AND-OSS-AUDIT.md, ADR-0004, ADR-0011, lunar_gis/analysis/ahp.py, lunar_gis/analysis/tools.py

---

## 1. Executive Summary

This document defines the methodology, mathematical contract, and implementation design for AHP sensitivity analysis in Lunar GIS. It resolves the scope question (M2 vs M3), selects a minimal defensible first implementation, defines deterministic perturbation and ranking policies, and establishes provenance requirements. **No implementation occurs in this task.**

**Key decisions:**
- Sensitivity analysis is **M3 functionality** (methodology defined in M2, implementation deferred)
- First scope: **one-at-a-time (OAT) weight perturbation** with deterministic sweep
- No Monte Carlo, no multi-parameter perturbation in first implementation
- Sensitivity lives in `lunar_gis/analysis/sensitivity.py`, depends only on `ahp.py`

---

## 2. M2/M3 Scope Decision

### 2.1 The question

M2-T01 identified sensitivity analysis as part of M2 scope. M2-T04 deferred it to M3+. This document resolves the conflict.

### 2.2 Analysis

**Arguments for M2:**
- MILESTONES.md lists "sensitivity analysis" under M2
- M2-T01 §4.1 states: "Sensitivity analysis → M2 core gated first; perturbation analysis as separate acceptance item"
- Completing AHP without sensitivity leaves the methodology incomplete

**Arguments for M3:**
- M2 AHP core (T02–T04) is stable and tested (409 tests, all quality gates pass)
- Sensitivity analysis adds a new data structure (`SensitivityResult`) and API surface
- Sensitivity depends on the AHP engine but does not change it
- M3 is defined as "MCE/Suitability" — sensitivity is a prerequisite for MCE robustness
- Implementing sensitivity in M2 risks destabilizing a completed milestone

### 2.3 Decision

**Sensitivity analysis is M3 functionality.** The methodology is defined here in M2. Implementation occurs in M3-T01 (or equivalent M3 entry point).

**Rationale:**
1. The M2 AHP core is complete and frozen. Adding sensitivity changes the `analysis` module's public API and data structures.
2. MILESTONES.md §10 states: "Do not implement future-phase features opportunistically."
3. The M2/M3 boundary is the natural seam: M2 = "compute AHP weights", M3 = "analyze sensitivity of those weights".
4. This design document serves as the accepted specification for M3 implementation.

### 2.4 What this means

- M2 delivers: `ahp()` → `AHPResult` (done)
- M3 delivers: `sensitivity_ahp()` → `SensitivityResult` (to be implemented)
- The `analysis` module will gain a new file `sensitivity.py` in M3
- No changes to `ahp.py`, `tools.py`, or `processing/` in M2

---

## 3. Definition of Sensitivity Analysis

### 3.1 Scope

AHP sensitivity analysis concerns the **sensitivity of criterion weights and their ranking** to perturbations in the input pairwise comparison matrix or derived weights. It answers:

> "How much can a pairwise judgment change before the criterion ranking changes?"

### 3.2 What it is NOT

- **NOT MCE/suitability sensitivity** — that concerns raster criteria, normalization, weighted overlay, spatial outputs (M3+)
- **NOT rank reversal from adding/removing alternatives** — that is a structural AHP property, not a sensitivity method
- **NOT Monte Carlo robustness** — that requires nondeterministic sampling (deferred)
- **NOT fuzzy AHP** — that extends the scale itself (deferred)

### 3.3 In-scope analysis types

| Type | Description | Priority |
|------|-------------|----------|
| **OAT weight perturbation** | Sweep one criterion weight from 0→1 while holding others proportionally fixed | First |
| **OAT pairwise perturbation** | Change one pairwise comparison `a[i][j]` across its valid range, recompute weights | Second |
| **Rank stability interval** | Find the perturbation range where ranking does not change | First |
| **Crossover/threshold detection** | Identify exact perturbation values where ranking changes | First |

### 3.4 Out-of-scope (deferred)

| Type | Reason |
|------|--------|
| Multi-parameter perturbation | Combinatorial explosion; defer to M5+ |
| Monte Carlo simulation | Nondeterministic; conflicts with deterministic core |
| Sensitivity of alternatives ranking | Requires M3 alternative-level AHP |
| Partial derivative sensitivity | Complex; defer to expert use cases |
| Fuzzy AHP sensitivity | Extends the scale model; defer |

---

## 4. AHP Sensitivity Methodologies

### 4.1 One-at-a-time (OAT) weight perturbation

**Mathematical definition:** Given baseline weights `w = (w₁, ..., wₙ)` from the AHP engine, perturb a single weight `wₖ` by `δ ∈ [-wₖ, 1-wₖ]` while redistributing the remaining mass proportionally:

```
w'ₖ = wₖ + δ
w'ᵢ = wᵢ × (1 - w'ₖ) / (1 - wₖ)  for i ≠ k
```

Recompute `w'` at each step. Report ranking at each step.

**Strengths:** Simple, deterministic, interpretable, covers all criteria
**Limitations:** Only tests one variable at a time; miss interactions
**Computational cost:** O(n × S) where S = number of steps per criterion
**Deterministic:** Yes — sweep is uniform, reproducible

### 4.2 OAT pairwise judgment perturbation

**Mathematical definition:** Given baseline matrix `A`, perturb a single upper-triangle entry `a[i][j]` across its valid range (respecting Saaty scale and reciprocity). Recompute `A'`, run `ahp()`, report weights.

**Strengths:** Directly tests judgment sensitivity; preserves matrix structure
**Limitations:** Only tests one judgment at a time; requires valid matrix at each step
**Computational cost:** O(n² × S × convergence_cost)
**Deterministic:** Yes — sweep is uniform, reproducible

### 4.3 Stability interval computation

**Mathematical definition:** For each criterion pair (i, j), find the range of `δ` such that `rank(w') = rank(w)` (i.e., `w'ᵢ > w'ⱼ` iff `wᵢ > wⱼ`).

**Strengths:** Precise; identifies exactly how robust a ranking is
**Limitations:** Requires binary search or analytical computation
**Computational cost:** O(n² × log(precision))
**Deterministic:** Yes

### 4.4 Rank reversal detection

**Mathematical definition:** Identify all crossover points where `w'ᵢ = w'ⱼ` for some pair (i, j) as perturbation varies.

**Strengths:** Complete picture of ranking fragility
**Limitations:** May find no crossover (robust) or many (fragile)
**Computational cost:** Same as stability interval
**Deterministic:** Yes

---

## 5. Selected First Implementation Scope

### 5.1 Primary method: OAT weight perturbation with stability intervals

The first implementation combines:
1. OAT weight sweep (section 4.1)
2. Stability interval computation (section 4.3)
3. Crossover detection (section 4.4)

This is the most defensible minimal scope because:
- It is fully deterministic
- It has well-established methodology (Saaty 1980, Pankratova & Nedashkovskaya 2016)
- It covers the most common sensitivity question: "how robust is my ranking?"
- It does not require MCE, alternatives, or spatial data
- It is computationally tractable for n ≤ 10

### 5.2 Secondary method: OAT pairwise perturbation

Included as a secondary method because:
- It directly tests judgment sensitivity (not just weight sensitivity)
- It preserves matrix validity (reciprocal, Saaty scale)
- It is the methodology used in Expert Choice and most AHP software

### 5.3 Excluded from first implementation

| Method | Reason |
|--------|--------|
| Multi-parameter | Combinatorial; defer to M5+ |
| Monte Carlo | Nondeterministic |
| Partial derivatives | Complex; defer |
| Fuzzy sensitivity | Extends scale model |

---

## 6. Mathematical Contract

### 6.1 Constants

```python
NEAR_TIE_TOL = 1e-6  # weight distance below which two criteria are "near-tied"
SENSITIVITY_POLICY_VERSION = "1.0"
RANKING_POLICY_VERSION = "1.0"
```

### 6.2 Inputs

```python
@dataclass(frozen=True)
class SensitivityInput:
    """Input for AHP sensitivity analysis."""

    criteria: list[str]  # n criterion names
    matrix: list[list[float]]  # n×n reciprocal pairwise matrix
    method: SensitivityMethod  # OAT_WEIGHT or OAT_PAIRWISE
    perturbation_range: tuple[float, float]  # (min_delta, max_delta) absolute offsets
    num_steps: int  # number of sweep steps (≥ 5)
    target_criteria: list[str] | None = None  # subset to analyze (None = all)
```

**Constraints:**
- `criteria` and `matrix` must be valid AHP inputs (pass `validate_ahp_input`)
- `method` ∈ {`OAT_WEIGHT`, `OAT_PAIRWISE`}
- `perturbation_range` must be within `(-1.0, 1.0)` (absolute weight offsets)
- `num_steps` ∈ [5, 100]
- `target_criteria` ⊆ `criteria` or `None`

### 6.3 Outputs

The complete data model (consolidated from all sections):

```python
@dataclass(frozen=True)
class CriterionSensitivity:
    """Sensitivity result for a single criterion."""

    criterion: str
    baseline_weight: float
    stability_lower: float  # lower bound of stability interval
    stability_upper: float  # upper bound of stability interval
    crossover_points: list[float]  # perturbation values where ranking changes
    perturbation_values: list[float]  # sampled perturbation values
    perturbed_weights: list[list[float]]  # weights at each perturbation step
    perturbed_rankings: list[list[int]]  # rankings at each perturbation step
    consistency_flags: list[str]  # consistency flag at each step
    consistency_ratios: list[float]  # CR at each step


@dataclass(frozen=True)
class SensitivityResult:
    """Complete sensitivity analysis result."""

    criteria: list[str]
    baseline_weights: list[float]
    baseline_ranking: list[int]
    criterion_results: list[CriterionSensitivity]
    method: SensitivityMethod
    numerical_policy_version: str
    engine_version: str
    input_hash: str  # SHA-256 of {criteria, matrix}
    perturbation_range: tuple[float, float]
    num_steps: int
    target_criteria: list[str] | None
    ranking_policy_version: str
    consistency_policy_version: str
    near_ties: list[tuple[str, str]]  # pairs of criteria with near-equal weights
```

### 6.3 Ranking output format

Rankings are produced as a list of integers where:
- Rank 0 = highest weight (best)
- Rank 1 = second highest
- ...
- Rank n-1 = lowest weight
- Ties receive the same rank (see section 8)

---

## 7. Perturbation Policy

### 7.1 OAT weight perturbation

For criterion `k` with baseline weight `wₖ`:

1. Define sweep: `δ ∈ [-wₖ + ε, 1 - wₖ - ε]` with `ε = FLOAT_COMPARE_EPS`
2. At each step `s`:
   - `w'ₖ = wₖ + δₛ`
   - For `i ≠ k`: `w'ᵢ = wᵢ × (1 - w'ₖ) / (1 - wₖ)`
   - Normalize: `w' = w' / sum(w')`
3. Compute ranking of `w'`
4. Detect crossover: ranking differs from baseline

### 7.2 OAT pairwise perturbation

For upper-triangle entry `a[i][j]`:

1. Define sweep: `a'[i][j] ∈ [SAATY_SCALE_MIN, SAATY_SCALE_MAX]` stepping through valid Saaty values
2. At each step:
   - Set `a'[i][j] = value`, `a'[j][i] = 1/value`
   - Run `ahp(criteria, A')` → weights
   - Compute ranking
3. Detect crossover

### 7.3 Invalid perturbation handling

If a perturbation produces an invalid AHP matrix:
- For OAT weight: this cannot happen (weights are always valid)
- For OAT pairwise: skip steps that produce invalid matrices; record `None` for that step

### 7.4 Step calculation

```python
step_size = (max_delta - min_delta) / (num_steps - 1)
perturbation_values = [min_delta + i * step_size for i in range(num_steps)]
```

### 7.5 Floating-point policy

- Use existing `FLOAT_COMPARE_EPS = 1e-9` for comparisons
- Weights are not re-normalized beyond the existing AHP engine normalization
- Crossover detection: `|w'ᵢ - w'ⱼ| < FLOAT_COMPARE_EPS` → tie

---

## 8. Ranking Policy

### 8.1 Ranking definition

Given weights `w = (w₁, ..., wₙ)`, the ranking is the permutation that sorts weights in descending order. Rank 0 = highest weight.

### 8.2 Tie handling

Two weights `wᵢ` and `wⱼ` are tied if `|wᵢ - wⱼ| < FLOAT_COMPARE_EPS`. Tied criteria receive the same rank.

**Tie-breaking:** No artificial tie-breaking. Ties are reported as ties.

### 8.3 Near-tie detection

A near-tie occurs when `|wᵢ - wⱼ| < NEAR_TIE_TOL` where `NEAR_TIE_TOL = 1e-6`. Near-ties are flagged in the output as `near_ties: list[tuple[str, str]]`.

### 8.4 Rank change definition

A rank change occurs when the ranking at perturbation `δ` differs from the baseline ranking. Specifically, for any pair `(i, j)`:
- Baseline: `wᵢ > wⱼ` (i ranked above j)
- Perturbed: `w'ᵢ ≤ w'ⱼ` (i no longer ranked above j)

### 8.5 Stability interval

**Global stability interval:** The range of perturbation `δ` for criterion `k` such that the *entire* ranking remains unchanged. Under OAT weight perturbation, the non-perturbed criteria never cross each other (their ratios are preserved), so the global stability interval equals the pairwise intervals for all pairs involving criterion `k`.

For criterion `k` relative to criterion `j` (where `wₖ > wⱼ`):
```
δ_upper = max δ such that w'ₖ(δ) > w'ⱼ(δ) for all δ ∈ [0, δ]
δ_lower = min δ such that w'ₖ(δ) > w'ⱼ(δ) for all δ ∈ [δ, 0]
```

The overall stability interval for criterion `k` is:
```
[δ_lower, δ_upper] where δ_lower = max over all j of pairwise δ_lower(k,j)
                      and δ_upper = min over all j of pairwise δ_upper(k,j)
```

If no crossover exists with any criterion, the interval is `(-wₖ + ε, 1 - wₖ - ε)` (the full sweep range).

---

## 9. Consistency Interaction

### 9.1 Design decision

When a pairwise perturbation produces a matrix with `REVISE_REQUIRED` consistency:

**The result is reported but flagged.** Specifically:

1. All results are computed and included in the output
2. Each `CriterionSensitivity` includes a `consistency_flags: list[str]` field tracking the consistency flag at each perturbation step
3. Steps with `REVISE_REQUIRED` are flagged but NOT excluded
4. The baseline result remains the reference for ranking comparison
5. Downstream consumers must explicitly check consistency flags

**Rationale:**
- Excluding inconsistent results would create gaps in the sensitivity curve
- The user needs to see that some perturbations produce inconsistent judgments
- The consistency flag is metadata, not a filter
- This matches how Expert Choice and other AHP tools handle this case

### 9.2 Design decision

When a pairwise perturbation produces a matrix with `REVISE_REQUIRED` consistency:

**The result is reported but flagged.** Specifically:

1. All results are computed and included in the output
2. Each `CriterionSensitivity` includes `consistency_flags` and `consistency_ratios` fields tracking consistency at each perturbation step
3. Steps with `REVISE_REQUIRED` are flagged but NOT excluded
4. The baseline result remains the reference for ranking comparison
5. Downstream consumers must explicitly check consistency flags

**Rationale:**
- Excluding inconsistent results would create gaps in the sensitivity curve
- The user needs to see that some perturbations produce inconsistent judgments
- The consistency flag is metadata, not a filter
- This matches how Expert Choice and other AHP tools handle this case

---

## 10. Determinism

### 10.1 Perturbation sequence generation

- Sweep values are generated as: `min_delta + i * step_size` for `i ∈ [0, num_steps)`
- `step_size = (max_delta - min_delta) / (num_steps - 1)`
- All values are computed in Python `float` (IEEE 754 double)

### 10.2 Ordering

- Criteria are processed in input order
- Pairwise perturbations iterate upper triangle in row-major order
- Results are returned in the same order as input criteria

### 10.3 Comparison tolerance

- `FLOAT_COMPARE_EPS = 1e-9` (existing from ahp.py)
- `NEAR_TIE_TOL = 1e-6` (new constant for sensitivity)

### 10.4 Reproducibility

- Identical inputs → identical outputs (no randomness, no external state)
- Determinism is guaranteed by: pure computation, no I/O, no randomness
- The `input_hash` in the result enables verification of input equivalence

### 10.5 No Monte Carlo

Monte Carlo methods are explicitly excluded from the first implementation. If Monte Carlo sensitivity is needed in the future, it should be a separate function with explicit nondeterminism labeling.

---

## 11. Provenance

### 11.1 Required provenance fields

```python
@dataclass(frozen=True)
class SensitivityResult:
    # ... result fields ...
    numerical_policy_version: str  # "1.0" (same as ahp.py)
    engine_version: str  # same as ahp.py
    input_hash: str  # SHA-256 of baseline matrix JSON
    method: str  # "OAT_WEIGHT" or "OAT_PAIRWISE"
    perturbation_range: tuple[float, float]
    num_steps: int
    ranking_policy_version: str  # "1.0"
    consistency_policy_version: str  # "1.0"
```

### 11.2 Version constants

```python
SENSITIVITY_POLICY_VERSION = "1.0"
RANKING_POLICY_VERSION = "1.0"
```

### 11.3 Input hash

The `input_hash` is the SHA-256 of the canonical JSON of `{criteria, matrix}`, matching `_canonical_input_hash()` in `ahp.py`. This enables verification that the sensitivity analysis was performed on the same input as the baseline AHP result.

---

## 12. Architecture

### 12.1 Module location

```
lunar_gis/analysis/
    __init__.py
    ahp.py              # AHP engine (frozen, M2)
    sensitivity.py      # Sensitivity analysis (M3, NEW)
    tools.py            # AHP ToolSpec adapter (frozen, M2)
```

### 12.2 Dependency direction

```
sensitivity.py → ahp.py (imports ahp, AHPResult, constants)
sensitivity.py → utils (imports nothing new)
```

**sensitivity.py does NOT depend on:**
- QGIS (no `qgis.core`, no Processing)
- `agent` module
- `ai` module
- `data` module
- `project` module
- Network
- Filesystem

### 12.3 Relationship to AHP engine

The sensitivity module calls `ahp()` repeatedly with perturbed inputs. It does NOT:
- Modify the AHP engine
- Access AHP internal state
- Depend on AHP implementation details
- Reimplement any AHP mathematics

The `ahp()` function is treated as a black box: matrix → weights.

### 12.4 ToolSpec integration (deferred)

In M3, a `SENSITIVITY_TOOL_SPEC` can be added to `tools.py` following the same pattern as `AHP_TOOL_SPEC`. This is deferred to M3 implementation.

### 12.5 Processing integration (deferred)

In M3+, a `SensitivityAlgorithm` can be added to `lunar_gis/processing/`. This is deferred.

---

## 13. OSS Audit

### 13.1 Candidates

| Library | License | Methodology | Dependencies | Reuse Decision |
|---------|---------|-------------|--------------|----------------|
| **PySensMCDA** | MIT | Weight/matrix/ranking sensitivity | numpy | REFERENCE-ONLY |
| **AhpAnpLib** | MIT | Supermatrix sensitivity | numpy | REFERENCE-ONLY |
| **krispy** | MIT | OAT criteria removal sensitivity | numpy | REFERENCE-ONLY |
| **pymcdm** | MIT | MCDM methods (no sensitivity) | numpy | REJECT |
| **pyDecision** | GPL-3.0 | AHP + sensitivity | numpy, pandas | REJECT (license) |
| **scikit-criteria** | BSD-3 | MCDM + rank reversal | numpy, scipy | REJECT (scope) |
| **criterium-mcp** | MIT | AHP + sensitivity | numpy | REJECT (MCP/LLM scope) |

### 13.2 Detailed assessment

**PySensMCDA (REFERENCE-ONLY)**
- Repository: github.com/jwieckowski/pysensmcda
- License: MIT (verified)
- Version: v1.0.2 (SoftwareX 2024 paper version)
- Quality: Well-structured, peer-reviewed (SoftwareX 2024), 8 modules
- Relevance: Implements OAT weight perturbation (percentage modification, range modification), ranking sensitivity, and perturbation generation — directly applicable to Lunar M3 scope
- Dependency: numpy (Lunar GIS is stdlib-only for AHP)
- Decision: REFERENCE-ONLY — methodology reference, not runtime dependency. PySensMCDA uses numpy arrays internally; Lunar GIS uses plain Python lists. Do not copy code — reimplement in stdlib.

**AhpAnpLib (REFERENCE-ONLY)**
- Repository: github.com/CDFLab/AhpAnpLib
- License: MIT (verified)
- Quality: Mature, used in ISAHP 2024 workshop
- Relevance: Supermatrix sensitivity, ANP support
- Decision: REFERENCE-ONLY — ANP is out of scope; methodology for AHP sensitivity is useful as reference.

**krispy (REFERENCE-ONLY)**
- Repository: github.com/kgearhar/krispy (unverified at audit date — may be private/defunct)
- License: MIT (verified via PyPI)
- Quality: Minimal, single-author, no tests
- Relevance: OAT criteria removal sensitivity
- Decision: REFERENCE-ONLY — too minimal for production use; methodology is standard.

**pyDecision (REJECT)**
- License: GPL-3.0 (compatible with Lunar GIS GPL-2.0-or-later, but rejected for other reasons)
- Decision: REJECT (LLM coupling + dependency scope) — native ChatGPT/Gemini integration violates AGENTS.md:2; 80+ method surface is oversized coupling; numpy+scipy+deps are unnecessary runtime weight.

### 13.3 No dependencies added

All candidates use numpy. Lunar GIS sensitivity analysis will be implemented in pure Python (stdlib only), consistent with the existing AHP engine. No runtime dependencies are added.

**Methodology leakage warning:** REFERENCE-ONLY means methodology reference only. Do not copy code — reimplement in stdlib. PySensMCDA and pymcdm use numpy arrays internally; Lunar GIS uses plain Python lists. Copying numpy-based patterns would violate the stdlib-only policy.

---

## 14. Testing Strategy

### 14.1 Test categories

| Category | Description | Count |
|----------|-------------|-------|
| Zero perturbation | `δ = 0` → ranking unchanged, weights unchanged | 2 |
| Small perturbation | `δ = 0.01` → ranking unchanged (for robust cases) | 2 |
| Large perturbation | `δ = 0.5` → ranking may change | 2 |
| Stability interval | Verify computed interval matches analytical expectation | 2 |
| Crossover detection | Verify crossover points are correctly identified | 2 |
| Ties | Weights that are exactly equal → same rank | 2 |
| Near-ties | Weights very close → near-tie flagged | 1 |
| Invalid matrix (pairwise) | Perturbation produces invalid matrix → skipped | 1 |
| Determinism | Identical inputs → identical outputs | 2 |
| Consistency flags | REVISE_REQUIRED perturbations are flagged | 1 |
| Bounds | Perturbation at min/max of range | 2 |
| Full sweep | All criteria perturbed, all steps computed | 1 |

**Estimated: 20 tests**

### 14.2 Reference/oracle cases

**Oracle 1: 3×3 consistent matrix**
```
criteria = ["A", "B", "C"]
matrix = [[1, 3, 5], [1/3, 1, 3], [1/5, 1/3, 1]]
baseline weights ≈ [0.637, 0.258, 0.105]
baseline ranking = [0, 1, 2]
```
- Perturb wₖ: stability interval for A vs B: δ ∈ [-0.221, 0.363] (A stays above B)
- Crossover A↔B: w'ₐ = w'ᵦ ≈ 0.4157 at δ ≈ -0.2213
- Crossover A↔C: w'ₐ = w'c ≈ 0.465 at δ ≈ -0.172 (A stays above C over wider range)

**Oracle 2: 3×3 near-tie matrix**
```
criteria = ["A", "B", "C"]
matrix = [[1, 1.1, 5], [1/1.1, 1, 3], [1/5, 1/3, 1]]
baseline weights ≈ [0.476, 0.366, 0.158]
baseline ranking = [0, 1, 2]
```
- Crossover A↔B: w'ₐ = w'ᵦ ≈ 0.421 at δ ≈ -0.055 (narrow stability interval)
- Stability interval for A: [-0.055, 0.524] (much narrower than Oracle 1)
- Small perturbation δ = -0.01: ranking unchanged [0, 1, 2]

**Oracle 3: 2×2 exact formula**
```
criteria = ["X", "Y"]
matrix = [[1, 3], [1/3, 1]]
weights = [0.75, 0.25] exactly
```
- OAT weight perturbation: straightforward (only 2 criteria)
- Crossover at w'ₓ = w'ᵧ = 0.5

### 14.3 Quality gates

All existing quality gates apply:
- `pytest -q` — all tests pass
- `ruff check .` — no lint errors
- `ruff format --check .` — formatted
- `mypy lunar_gis` — no type errors
- `bandit -c pyproject.toml -r lunar_gis` — no security issues
- `python -m build` — builds successfully
- Packaging tests pass

---

## 15. Deferred Methods

| Method | Reason for deferral | Target milestone |
|--------|---------------------|------------------|
| Multi-parameter perturbation | Combinatorial explosion | M5+ |
| Monte Carlo weight sampling | Nondeterministic | M5+ (if explicitly needed) |
| Partial derivative sensitivity | Complex analytical requirement | M5+ |
| Fuzzy AHP sensitivity | Extends scale model | M5+ |
| Alternative-level sensitivity | Requires M3 alternatives | M3+ |
| Rank reversal from adding alternatives | Structural property, not sensitivity | Deferred |
| Tornado diagram visualization | Requires M7 cartography | M7+ |
| Sensitivity report generation | Requires M8 reports | M8+ |

---

## 16. Implementation Recommendation

### 16.1 Implementation order

1. **M3-T01 (or M3 entry):** Create `lunar_gis/analysis/sensitivity.py` with `SensitivityInput`, `SensitivityResult`, `CriterionSensitivity` dataclasses
2. **M3-T01:** Implement OAT weight perturbation
3. **M3-T01:** Implement stability interval computation
4. **M3-T01:** Implement crossover detection
5. **M3-T01:** Write 35+ tests
6. **M3-T02:** Add `SENSITIVITY_TOOL_SPEC` to `tools.py`
7. **M3-T02:** Add sensitivity handler and registration
8. **M3-T03:** Add Processing algorithm with progress/cancellation support (`feedback.setProgress()`, `feedback.isCanceled()`)

### 16.2 API design

```python
# lunar_gis/analysis/sensitivity.py


def sensitivity_ahp(
    criteria: list[str],
    matrix: list[list[float]],
    method: str = "OAT_WEIGHT",  # or "OAT_PAIRWISE"
    perturbation_range: tuple[float, float] = (-0.3, 0.3),
    num_steps: int = 20,
    target_criteria: list[str] | None = None,
) -> SensitivityResult:
    """Run deterministic AHP sensitivity analysis."""
    ...
```

### 16.3 Key design principles

1. **Black-box AHP:** Call `ahp()` repeatedly; never modify it
2. **Pure Python:** No numpy, no scipy, no external dependencies
3. **Deterministic:** No randomness, no external state
4. **Self-contained:** All math in `sensitivity.py`; no QGIS dependency
5. **Provenance-complete:** Full audit trail in `SensitivityResult`
6. **Thread-safe:** `ahp()` is a pure function with no shared mutable state; calling it from a Processing background thread is safe

---

## 17. References

1. Saaty, T.L. (1980). *The Analytic Hierarchy Process*. McGraw-Hill.
2. Saaty, T.L. (2001). *Decision Making with the Analytic Network Process*. Springer.
3. Pankratova, N.D. & Nedashkovskaya, N.I. (2016). "Sensitivity Analysis of a Decision-Making Problem Using the AHP." *Informatics and Automation*, 15, 366–382.
4. Triantaphyllou, E. & Sánchez, A. (1997). "A Sensitivity Analysis Approach for Some Deterministic Multi-Criteria Decision-Making Methods." *Decision Sciences*, 28(1), 151–194.
5. Ivanco, M. et al. (2017). "Sensitivity Analysis Method to Address User Disparities in the AHP." *Expert Systems with Applications*, 90, 111–126.
6. Saaty, T.L. (2001). "Decision-Making with the AHP: Why is the Principal Eigenvector Necessary?" *ISAHP 2001*.
7. Więckowski, J. et al. (2024). "PySensMCDA: A Novel Tool for Sensitivity Analysis in Multi-Criteria Problems." *SoftwareX*, 27, 101746.
8. Sowlati, T. et al. (2010). "Developing a Mathematical Programming Model for Sensitivity Analysis in AHP." *International Journal of Management Science and Engineering Management*, 5(3).
9. Almeida, R.G. et al. (2021). "Some Mathematical Comments About the AHP: Part II — Practical Analysis." *Pesquisa Operacional*.
10. Górecki, J. et al. (2023). "Robustness of Priority Deriving Methods for PCMs Against Rank Reversal." *Annals of Operations Research*.
