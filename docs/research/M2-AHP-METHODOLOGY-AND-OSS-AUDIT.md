# M2 AHP Methodology & OSS Reuse Audit

**Date researched:** 2026-09-14
**Starting commit:** `e5d6381` `feat: add controlled tool execution boundary` (M1 COMPLETE)
**Auditor:** Primary engineering agent, with evidence from primary AHP literature (Saaty), upstream GitHub/PyPI, and plugins.qgis.org.
**Scope:** RESEARCH ONLY — no production code, no dependency, no integration, no M2-T02 implementation.

---

## 1. Executive Summary

Lunar GIS must **own** a small, deterministic, stdlib-only AHP engine and **not** become a thin wrapper around any existing AHP library or QGIS suitability plugin. The audit of 9 candidates finds:

* **BUILD:** Lunar GIS's own AHP engine in `lunar_gis/analysis/` — principal right eigenvector via power iteration, Saaty 1–9 scale, Saaty canonical RI table, CR ≤ 0.10 gate. No external candidate satisfies the 12 governance rules (zero-dependency, offline-deterministic, no LLM math, GPL-2.0-or-later compatible) without adaptation cost exceeding build cost.
* **REFERENCE-ONLY (ideas + test oracles):** `AHPy` (MIT; eigenvector method, dual RI tables, worked examples usable as independent test oracles), `pymcdm` (MIT; eigenvector AHP with 1–9 scale validation and CR < 0.1 gate), QGIS suitability plugins (staged-wizard UX, CR-gated weighting, hard-constraint composition — M3-relevant patterns only).
* **REJECT for runtime:** `pyDecision` (GPL-3.0; LLM-integrated; oversized surface), `scikit-criteria` (no core AHP pairwise engine), `EasyAHP` (QGIS 3-only, no QGIS 4 support; GPL-3.0), narrow/experimental single-purpose suitability plugins.

**Canonical methodology decision:** principal **right eigenvector** (Saaty's method) computed by deterministic **power iteration**; consistency via **λmax → CI → CR** against the **Saaty canonical RI table (n = 1..10)** with **CR ≤ 0.10** accept, **0.10 < CR ≤ 0.20** tolerable-with-warning (Lunar extension, see §6), **CR > 0.20** revise-required. Incomplete matrices are **rejected** (no imputation). Matrix sizes outside 1..10 are **rejected** (no silent extrapolation).

---

## 2. AHP Methodology

The Analytic Hierarchy Process (Saaty, 1977, 1980) derives ratio-scale priorities from pairwise comparisons. The decision maker compares criteria two at a time, stating how many times more important one is than the other; the reciprocal matrix of these judgments yields a priority vector (its principal eigenvector), and the deviation of the principal eigenvalue from the matrix order measures inconsistency.

Lunar GIS implements **criteria weighting only** in M2 (one pairwise matrix → one priority vector + consistency report). Hierarchy synthesis (composing several matrices across levels) and alternative scoring are **deferred** to M3+; the engine is deliberately single-matrix.

---

## 3. Pairwise Comparison Scale

Lunar GIS adopts Saaty's **fundamental 1–9 scale**, derived from stimulus–response psychophysics and the homogeneity requirement that compared elements be of the same order of magnitude (Saaty 2001; the scale's upper bound of 9 follows from eigenvector stability conditions).

| Value | Meaning |
|-------|---------|
| 1 | Equal importance |
| 3 | Moderate importance of one over another |
| 5 | Strong importance |
| 7 | Very strong importance |
| 9 | Extreme importance |
| 2, 4, 6, 8 | Intermediate values (compromises between adjacent judgments) |
| 1/2 … 1/9 | Reciprocals: if *i* vs *j* is *k*, then *j* vs *i* is *1/k* |

**Decision:** M2 input judgments are restricted to exactly the 17 scale values {1..9} ∪ {1/2..1/9}. Non-scale reals (e.g. 2.5) are **rejected** at validation. Rationale: the RI table (§7) was simulated with the Saaty scale, so holding M2 inputs to the scale keeps CR semantics unambiguous in provenance. This is a **Lunar M2 input contract, not a Saaty mandate** — the eigenvector/CI/CR mathematics is defined for any positive reciprocal matrix, and Saaty/practice admit refined or aggregated off-scale judgments. M6 group aggregation (geometric mean of judgments) will require relaxing this contract; that relaxation needs its own methodology note. Scale membership is tested by nearest-value match within relative tolerance **1e-12** (`SCALE_MEMBERSHIP_TOL`), which also absorbs binary64 representation of exact fractions like 1/3.

---

## 4. Reciprocal Matrix Rules

For an *n*×*n* judgment matrix *A = (aᵢⱼ)*:

* **Square:** *A* must be *n*×*n*. Non-square input is rejected.
* **Diagonal:** *aᵢᵢ = 1* exactly (an element is equal to itself; no tolerance).
* **Reciprocity:** *aⱼᵢ = 1/aᵢⱼ*. Validated as *|aᵢⱼ · aⱼᵢ − 1| ≤ 1e-9* (relative). Violations are rejected as contradictory input, not repaired.
* **Positivity:** every entry must be finite and strictly positive. Zero, negative, NaN, or infinite entries are rejected.
* **Scale membership:** every entry must be one of the 17 scale values (§3). Off-scale entries are rejected.
* **Consistency (aᵢⱼ·aⱼₖ = aᵢₖ) is NOT required.** Inconsistency is allowed and measured (§6). A consistent matrix has λmax = *n*; an inconsistent (but still reciprocal) matrix has λmax > *n* (Saaty 1977, Theorem: λmax ≥ *n*).

Invalid matrices are rejected with specific errors (non-square, bad diagonal, reciprocity violation, non-positive/non-finite, off-scale value). The engine never repairs, rounds, or imputes input.

---

## 5. Priority-Vector Method Decision

**Canonical method: principal right eigenvector, computed by power iteration.**

Saaty selected and mathematically defended the principal right eigenvector as the technique for deriving the scale (*Aw = λmax·w*, normalized to sum 1). The Perron–Frobenius theorem guarantees a unique positive eigenvector for a positive reciprocal matrix. Alternatives considered:

1. **Normalized-column / row-average approximation** — rejected as canonical: it is an approximation that coincides with the eigenvector only for consistent matrices; adopting it would make Lunar's weights method-dependent on input consistency. Deferred as an optional future cross-check, never the source of truth.
2. **Geometric mean (row geometric mean / logarithmic least squares, Crawford & Williams 1985)** — rejected as canonical: a different estimator with different axiomatic properties; supporting two canonical estimators invites weight shopping. Deferred as a possible future alternative estimator behind an explicit method flag, not in M2.
3. **Direct eigensolver (numpy/scipy LAPACK)** — rejected: introduces a hard scientific-stack dependency into a QGIS plugin for a computation that power iteration handles deterministically in stdlib.

Power iteration (uniform start vector, L1 normalization, §8 tolerances) converges to the principal eigenvector for positive matrices and is fully reproducible without native dependencies. M2-T02 must cross-check its output against an independent oracle (AHPy/pymcdm or LAPACK, computed once in an isolated pinned environment and vendored as expected vectors — never a test-suite import or dependency) with acceptance `|w − w_ref|∞ < 1e-6` and CR within `1e-4`, accounting for AHPy's `precision=4` rounding and pymcdm's `CR < 0.1` vs Lunar `CR ≤ 0.10` gate difference, before sign-off. Self-computed values are regression fixtures only after that independent pass (§14 frozen oracles). M2-T02 must also assert the eigen-residual `‖Aw − λw‖∞` (not only the component-wise delta) at convergence.

---

## 6. Consistency Methodology

* **Maximum eigenvalue:** λmax = mean of *(Aw)ᵢ/wᵢ* over *i*, with *w* the normalized principal eigenvector. For a consistent matrix λmax = *n*; otherwise λmax > *n*.
* **Consistency index:** CI = (λmax − *n*) / (*n* − 1). The negative average of the non-principal roots; a single number capturing deviation from the consistent approximation (Saaty 1990).
* **Consistency ratio:** CR = CI / RI(*n*), with RI from §7.
* **Thresholds:** Saaty's canonical rule is CR ≤ 0.10 accept, else revise. Lunar adopts a three-tier flag enum with pinned strings — `ACCEPTABLE` (CR ≤ 0.10), `ACCEPTABLE_WITH_WARNING` (0.10 < CR ≤ 0.20), `REVISE_REQUIRED` (CR > 0.20):
  * CR ≤ 0.10 → **acceptable** (≥90% away from random).
  * 0.10 < CR ≤ 0.20 → **tolerable with warning (Lunar extension;** Saaty notes ~0.20 as tolerable in some contexts, but it is not the canonical rule**):** weights are still computed and returned, flagged `ACCEPTABLE_WITH_WARNING` with a revise recommendation.
  * CR > 0.20 → **revise required:** weights are still computed and returned (inconsistency is measured, not hidden), flagged `REVISE_REQUIRED`. The engine never refuses to compute; the caller decides whether to proceed — with the hard governance constraint that `REVISE_REQUIRED` weights must never be silently consumed downstream (M3 overlays, M5 planning): they require explicit human re-confirmation and audit of weights + CR + flag + input hash (§16.7).
* Threshold float comparison uses epsilon `FLOAT_COMPARE_EPS = 1e-9`: accept iff CR ≤ 0.10 + eps; warning iff CR ≤ 0.20 + eps. Boundary matrices (just below / at / just above 0.10 and 0.20) are mandatory M2-T02 fixtures.
* **Degenerate sizes (defined convention, not derivation):** *n* = 1 → weights [1.0], λmax = 1; CI = (λ−1)/0 is undefined so CI = CR = 0 **by definition**. *n* = 2 → any reciprocal 2×2 matrix is consistent (λmax = 2 exactly); CR = 0 **by definition** (RI(2) = 0; the engine short-circuits before any division). Engine results with n < 3 carry `trivial_consistency: true` in provenance.
* Improving consistency never means approaching ground truth (Saaty 1977): it means the judgments are closer to being logically related. Lunar's revision UX must not claim otherwise.

---

## 7. RI Policy

**Canonical source: Saaty's table** (500-sample simulation; reproduced in Saaty 1980 and *Theory and Applications of the ANP*, RWS 2005, p. 31), vendored with source tag `RI_SOURCE = "saaty-1980"`.

| n | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|----|
| RI | 0.00 | 0.00 | 0.58 | 0.90 | 1.12 | 1.24 | 1.32 | 1.41 | 1.45 | 1.49 |

* **n > 10: explicitly unsupported in M2.** The engine rejects larger matrices with `UNSUPPORTED_MATRIX_SIZE`. No silent extrapolation, no vendored extension tables. Rationale: Saaty's homogeneity axiom bounds comparable sets to a handful of elements ("items must be less than ten"); larger sets must be clustered/hierarchized, which is M3+ scope. (Donegan & Dodd 1991 extends RI to n = 100; adopting it is a deferred, explicit future decision, not a silent default.)
* **Alternative RI sets noted, not adopted:** Alonso & Lamata 2006 (n = 3: 0.5247 …), Forman, Donegan & Dodd. Documented here so a future RI-source flag has known candidates; M2 supports exactly one source to keep CR semantics unambiguous in provenance.
* **Minimum size:** n = 1 supported (trivial case, §6). n < 1 and non-square are rejected.

---

## 8. Numerical Policy

Deterministic, stdlib-only (`requires-python >= 3.10`, no numpy/scipy — cf. AGENTS.md:11 offline determinism and the zero-dependency `agent/` precedent):

* **Arithmetic:** IEEE-754 binary64 via Python `float`. No `Decimal`, no rationals internally (inputs may be given as exact fractions like `1/3`; they enter as the nearest binary64 value and tolerance policy absorbs this).
* **Power iteration:** start vector uniform (1/n); iterate *v ← Av/‖Av‖₁*; stop when max absolute component-wise change < **1e-12** or after **10,000** iterations (non-convergence → internal error, never a silent partial result). M2-T02 additionally asserts the eigen-residual `‖Aw − λw‖∞ < 1e-9` at convergence.
* **λmax estimator:** mean of *(Aw)ᵢ/wᵢ* (the standard Saaty estimator for non-symmetric reciprocal A; a Rayleigh quotient would be inappropriate). Requires converged strictly-positive *w* — the implementation asserts *wᵢ > 0* for all *i* before dividing (explicit div-by-zero guard, complementing the positivity check below).
* **Reciprocity tolerance:** *|aᵢⱼ·aⱼᵢ − 1| ≤ 1e-9* (relative, scale-aware: products near 1 by construction).
* **Diagonal:** exact `== 1.0` required.
* **Zero/near-zero:** the Perron vector of a positive matrix is strictly positive; any non-positive or non-finite weight component post-computation is an internal error (reject, do not clamp).
* **Invalid numerics:** NaN/±Inf/zero/negative/off-scale inputs rejected at validation with specific error codes before any computation.
* **Deterministic ordering:** criteria order is the input list order; never `set`/dict-order dependent. Matrix rows/columns follow criteria order.
* **Serialization:** canonical JSON with fixed key order (criteria, matrix, method, weights, lambda_max, CI, RI source/value, CR, threshold, flag, numerical policy id). Internal full precision retained; display rounding (6 decimals) applies only at presentation/serialization boundary and is recorded in provenance as `display_precision`.
* **No premature optimization:** clarity and auditability over speed; n ≤ 10 makes performance irrelevant.

---

## 9. Input Validation Policy

Accepted input: an ordered criteria list (non-empty, unique string names) plus a complete *n*×*n* matrix of finite positive scale values. Rejections (each with a distinct error code):

| Condition | Error |
|-----------|-------|
| Non-square / ragged matrix (incl. empty, 0×0, `None` rows) | `NON_SQUARE_MATRIX` |
| n < 1 or n > 10 | `UNSUPPORTED_MATRIX_SIZE` |
| Diagonal ≠ 1 exactly | `INVALID_DIAGONAL` |
| Non-positive, NaN, or infinite entry | `INVALID_NUMERIC_VALUE` |
| Entry outside the 17 scale values (nearest match beyond 1e-12 relative) | `OFF_SCALE_VALUE` |
| Reciprocity violation beyond 1e-9 | `RECIPROCITY_VIOLATION` |
| Missing entry / incomplete matrix | `INCOMPLETE_MATRIX` |
| Duplicate criterion name | `DUPLICATE_CRITERION` |
| Empty or whitespace-only criterion name | `EMPTY_CRITERION_NAME` |

Boundary disambiguation (numeric vs scale): `NaN`, `±Inf`, `0`, negatives, and non-numeric strings (e.g. `"3"`) → `INVALID_NUMERIC_VALUE`; finite positives outside the scale set (e.g. `2.5`, `10`) → `OFF_SCALE_VALUE`. A ragged/empty/non-list matrix fails shape before size (`NON_SQUARE_MATRIX`, never `UNSUPPORTED_MATRIX_SIZE`); a well-formed complete *n*×*n* matrix with n > 10 fails size (`UNSUPPORTED_MATRIX_SIZE`).

Validation order is fixed and documented: shape → size → criteria → diagonal → numeric finiteness/positivity → scale membership → reciprocity. First failure wins (deterministic error precedence). M2-T02 must include precedence-pair fixtures for every overlap (e.g. simultaneously non-square + off-scale input asserts `NON_SQUARE_MATRIX`).

---

## 10. Missing/Invalid Comparison Policy

* **Missing comparisons / incomplete matrices:** **REJECTED** (`INCOMPLETE_MATRIX`). Lunar M2 implements no completion method — not Harker's, not AHPy's cyclic-coordinates optimum. Rationale: imputation invents judgments the decision maker never made; no completion method is in M2 scope, and silent completion would violate AGENTS.md:2 (deterministic truth must be traceable to explicit input).
* **Invalid values:** rejected per §9; never coerced.
* **Contradictory reciprocals:** rejected (`RECIPROCITY_VIOLATION`); the engine does not prefer one triangle over the other.
* **Inconsistent matrices:** computed and flagged per §6; never silently accepted, never refused.
* **Unsupported sizes:** rejected (`UNSUPPORTED_MATRIX_SIZE`); clustering large criterion sets is M3+ methodology, not an engine workaround.

---

## 11. Determinism Requirements

* Same (criteria, matrix) input → byte-identical canonical result, independent of AI layer, network, session, QGIS state, or wall-clock.
* No RNG anywhere in the engine (RI is a vendored constant table, not simulated at runtime).
* No timestamps inside the mathematical result; session/time metadata attaches outside the engine (§12).
* Repeated execution determinism is a mandatory M2-T02 test (§16).

---

## 12. Provenance Requirements

Separate **mathematical provenance** (produced by the engine, deterministic) from **session metadata** (attached by the executor/provenance layer, non-deterministic):

Mathematical provenance (every AHP result carries all of):
* ordered input criteria; input pairwise matrix (as given)
* method id: `principal-right-eigenvector/power-iteration`, engine version
* priority vector (full precision) + normalization statement (sums to 1)
* λmax, CI, RI source (`saaty-1980`), RI value used, CR, threshold applied, acceptability flag
* numerical policy id/version (tolerances, iteration cap, start vector)
* power-iteration iteration count at convergence
* input hash (SHA-256 over canonical input JSON) for result↔input binding
* `display_precision` used at the serialization boundary

Session metadata (never inside the engine):
* session id, timestamp, ToolSpec name/version, QGIS/Lunar versions, workflow id — attached by `ControlledExecutor`/`provenance/` per AGENTS.md:8.

The engine emits plain value types only and must not import `provenance/` or `ai` at module level (DAG direction: `analysis` → `provenance`, never the reverse).

Criterion names are caller-supplied strings: treat as **untrusted** (sanitize before any LLM context; no eval/format-string/log-injection sink — cf. `SECURITY_MODEL.md` prompt-injection guidance for layer metadata) and **potentially sensitive** (minimize logging; they are covered by the input hash, and provenance retention/redaction policy is set in M2-T02).

The engine depends on nothing from the AI layer (AGENTS.md:2).

---

## 13. QGIS Architecture Boundary

Per ADR-0004, `analysis` owns deterministic AHP/MCE math and may import `project`, `data`, `provenance`, `utils`, `qgis.core`/`processing` — never `ai` for math. The M2 boundary is:

```text
User / AI request
        ↓
Tool Contract / Registry   (M1: validated, versioned ToolSpec)
        ↓
Controlled Executor        (M1: permission → confirmation → audit)
        ↓
Deterministic AHP engine   (M2: pure stdlib, no qgis import in math core)
        ↓
Validated AHP result       (weights + consistency + math provenance)
```

* **Pure AHP mathematics** (`analysis/ahp/` engine): stdlib only, no `qgis` import, testable via `pytest -q` without QGIS — same isolation precedent as M1's `agent/` boundary. Stdlib-only applies to M2 weight math only; M3 raster overlay MUST use `qgis.core`/`processing` per AGENTS.md:1.
* **QGIS/Processing integration:** deferred to M3 (criterion rasters, weighted overlay as Processing algorithms). M2 performs no raster I/O and adds no `QgsProcessingAlgorithm`.
* **Project/layer context:** M2 consumes only caller-supplied criteria names; no `QgsProject` reads inside the engine.
* **Provenance:** engine emits math provenance; `provenance/` + executor attach session metadata (M1 pattern).
* **Future AI orchestration (M5):** the AI layer may assemble *validated tool input* (criteria + judgments) from user intent; it must never calculate weights, λmax, CI, or CR itself (AGENTS.md:2, ADR-0002).

No new module-boundary edges are introduced **by M2-T01** (research only, no code/dependency/contract). Note for M2-T02: a `ToolSpec("lunar.ahp.compute_weights")` whose handler calls `analysis/ahp.py` WILL introduce an `agent → analysis` call edge, which ADR-0004 does not currently list (`agent` may import only `project, provenance, utils`). That edge MUST be assessed for an ADR-0004 addendum or new ADR under `docs/adr/README.md` criteria 1 (module boundaries), 2 (GIS API choice), and 4 (public ToolSpec contract) before T02 lands. "No ADR required" applies to T01 only and must not be carried forward.

---

## 14. OSS Reuse Audit

Method: for each candidate, repository URL → LICENSE file evidence where fetched (rows A–E: fetched 2026-09-14; rows F–I: provisional, plugin-page evidence only — marked) → implementation approach → decision. No dependency added; no code copied.

| # | Candidate | URL | License (evidence) | Approach | Relevance | Decision | Confidence |
|---|-----------|-----|--------------------|----------|-----------|----------|------------|
| A | AHPy (PhilipGriffith/AHPy, v2.1, 151 stars per 2026-09-14 snapshot) | https://github.com/PhilipGriffith/AHPy | **MIT** — LICENSE file fetched 2026-09-14 (© 2019 Philip Griffith); PyPI `MIT` | Principal-eigenvector weights w/ iteration cap + tolerance; hierarchy synthesis; optimal completion of missing comparisons (cyclic coordinates); dual RI tables (`dd`/Donegan & Dodd default, `saaty`); `precision=4` default rounding | Closest single-purpose AHP engine; RI tables + worked examples usable as independent test oracles | **REFERENCE-ONLY** — numpy+scipy hard deps violate zero-dependency policy; default 4-decimal rounding corrupts internal precision; missing-value imputation and hierarchy synthesis are out-of-M2-scope behaviors Lunar must not inherit | HIGH |
| B | pymcdm (kotbaton/pymcdm, v1.4.0) | https://github.com/kotbaton/pymcdm | **MIT** — LICENSE file fetched 2026-09-14 (© 2024–2026 Shekhovtsov/Kizielewicz); PyPI `MIT`; SoftwareX DOI 10.1016/j.softx.2023.101368 | Eigenvector AHP, 1–9 scale validation, CR < 0.1 gate, λmax = mean((Aw)/w); single-level criteria only | Methodologically closest to Lunar's M2 scope (eigenvector + scale validation + CR gate) | **REFERENCE-ONLY** — hard numpy dependency; `requires-python >= 3.11` excludes Lunar's 3.10 floor; broad MCDM surface (COMET/TOPSIS/…) is unneeded coupling; use docs/examples as cross-check oracle | HIGH |
| C | pyDecision (Valdecy/pyDecision, 361 stars per 2026-09-14 snapshot) | https://github.com/Valdecy/pyDecision | **GPL-3.0** — LICENSE file is GPL-3 text (© 2022 Valdecy Pereira); PyPI `GNU` | 80+ MCDA methods incl. AHP/ANP/Fuzzy-AHP; LLM (ChatGPT/Gemini) result interpretation built in | AHP present but bundled with LLM interpretation and 80-method surface | **REJECT** (runtime) — GPL-3.0 fails the M1-established runtime policy (cf. M1 audit §7: GPL-3.0 with QGIS GPL-2 distribution); native LLM integration violates AGENTS.md:2; oversized dependency surface | HIGH |
| D | scikit-criteria (quatrope, BSD-3) | https://github.com/quatrope/scikit-criteria | **BSD-3-Clause** — LICENSE.txt referenced from README/PyPI | Objective weighters only (entropy, CRITIC, MEREC, Gini, RANCOM); **no core pairwise-AHP engine** (`ahp_ext/` extra exists but was not evaluated — out of scope) | None for M2 AHP (relevant only to future objective-weighting work) | **REJECT** — no core AHP implementation to reuse or adapt | HIGH |
| E | EasyAHP (MSBilgin, plugins.qgis.org) | https://github.com/MSBilgin/EasyAHP | **GPL-3.0** — GitHub LICENSE file is GPL-3 text (corrected 2026-09-14; plugin page itself carries no license field) | AHP + WLC suitability wizard in QGIS | UX workflow ideas only | **REJECT** (runtime) — QGIS **3.0–3.99 only, no QGIS 4 support** (plugin page versions table, v1.0.11) **and** GPL-3.0 (double ground: platform + license) | HIGH |
| F | ahp_application (plugins.qgis.org) | https://plugins.qgis.org/plugins/ahp/ | Unverified | Full AHP-for-suitability app (DEM/climate/vector inputs, reclassification, restricted zones) | Single-purpose app, experimental | **REJECT** (runtime) / REFERENCE-ONLY for restricted-zone (hard-constraint) concept — M3 relevance only | MEDIUM (provisional) |
| G | ahp_analysis / Analyse Multicritère Hiérarchique (plugins.qgis.org) | https://plugins.qgis.org/plugins/ahp_analysis/ | Unverified | Raster AHP: pairwise UI → weights → CR → weighted raster | Narrow raster app | **REJECT** (runtime) / REFERENCE-ONLY for CR-gated raster weighting UX | MEDIUM (provisional) |
| H | PlanX Suitability Lab (YusufEminoglu) | https://gitlab.com/geospacephilo/planx_suitability_lab (canonical code host per plugin page; GitHub mirror exists but was not used for verification) | **Unknown — not verified; do not copy** (no license presumption made) | AHP weighting with CR acceptance flag; WLC/OWA suitability composition; hard-constraint masks (per plugin-page feature description; implementation details such as chunking/stack not verified) | M3 architecture reference (constraint handling, weight-audit pattern). Plugin page lists QGIS 3.28–4.99 (QGIS-4-ready, unlike EasyAHP) | **REFERENCE-ONLY** — M3 patterns only; no code reuse without license verification | MEDIUM (provisional) |
| I | Solar Site Suitability (AHP) (plugins.qgis.org) | https://plugins.qgis.org/plugins/solar_site_suitability/ | Unverified (provisional; app-level pattern reference only) | Spatial MCDA for solar siting: AHP weights validated by CR < 0.10 gate, boolean exclusion masks, viable-polygon extraction | CR-gating pattern (weights accepted only under CR < 0.10) | **REJECT** (runtime) / REFERENCE-ONLY for the CR-gate pattern | MEDIUM (provisional) |

**Not investigated (explicit):** R `ahp` package and spreadsheet AHP templates — out of scope for a Python/QGIS plugin runtime; no decision recorded.

### 14.1 Frozen regression oracles for M2-T02

The vectors below were computed by independent pure-stdlib power iteration (uniform start, L1 norm, tol 1e-12) on 2026-09-14. M2-T02 must vendor these full input matrices (not bare vectors) as fixtures **and** pass an independent cross-check (AHPy/pymcdm/LAPACK in an isolated pinned environment; vendored expected vectors only, never a test-suite import) with acceptance `|w − w_ref|∞ < 1e-6`, CR within `1e-4`, before sign-off. Self-computed values become regression fixtures only after that pass.

* **EX1 (consistent-ish 3×3, must be ACCEPTABLE):** criteria `["c1","c2","c3"]`, matrix `[[1,3,5],[1/3,1,3],[1/5,1/3,1]]` → w ≈ (0.636986, 0.258285, 0.104729), λmax ≈ 3.038511, CI ≈ 0.019256, CR ≈ 0.0332 (RI 0.58).
* **EX2 (2×2, trivially consistent):** matrix `[[1,4],[1/4,1]]` → w = (0.8, 0.2), λmax = 2.0 exactly, CR = 0.0 (short-circuit; also the n=2 RI-division-by-zero regression test).
* **EX3 (1×1, trivial):** matrix `[[1]]` → w = [1.0], λmax = 1.0, CR = 0.0 by definition.
* **EX4 (strongly inconsistent cyclic 3×3, must be REVISE_REQUIRED):** matrix `[[1,9,1/9],[1/9,1,9],[9,1/9,1]]` → w = (1/3, 1/3, 1/3), λmax ≈ 10.111111, CI ≈ 3.555556, CR ≈ 6.130268 (RI 0.58; CR ≫ 0.20 — engine must report, never silently accept).

Mandatory edge fixtures: n=10 accept / n=11 reject (`UNSUPPORTED_MATRIX_SIZE`); n=0 and empty-matrix reject; ragged rows (`NON_SQUARE_MATRIX`); duplicate / empty / whitespace-only names (`DUPLICATE_CRITERION` / `EMPTY_CRITERION_NAME`); reciprocity at `|ab−1| = 1e-9 ± ε` both sides; diagonal `1.0 ± ε` (exact `== 1.0` required); `2.5`, `10`, `NaN`, `Inf`, `0`, `-3`, `"3"` (numeric-vs-scale boundary); CR boundary matrices just below / at / just above 0.10 and 0.20; display-vs-internal precision (weights sum to 1 pre-rounding; `display_precision` in provenance); input-order stability; input-hash + iteration-count determinism across repeated runs. Non-convergence (10k cap → internal error) is unreachable for Perron-positive matrices without fault injection — cover via a fault-injected iteration cap, not by weakening the engine.

**Overall:** BUILD own engine. The two MIT libraries (AHPy, pymcdm) are legally reusable but technically unsuitable as runtimes (numpy/scipy deps, Python floor, rounding/imputation behaviors); their value is as **independent test oracles** for M2-T02. GPL-3.0 (pyDecision) is excluded by standing M1 policy. QGIS plugins contribute UX/architecture patterns only.

---

## 15. License Analysis

* Lunar GIS is **GPL-2.0-or-later** (`LICENSE` + `lunar_gis/LICENSE` byte-equal, per M1 audit). Per AGENTS.md:12, no external code is copied without license review — **this task copies none**.
* **MIT (AHPy, pymcdm):** permissive and GPL-2.0-or-later-compatible, but compatibility is moot: vendoring is rejected on technical grounds (§14), so no attribution obligation arises. If M2-T02 later vendors RI *values* (facts, not expression), no license obligation attaches to numerical constants; the source is still cited in provenance (`saaty-1980`).
* **GPL-3.0 (pyDecision):** excluded for runtime by the M1-established policy (GPL-3.0 code must not be vendored into the GPL-2-family QGIS plugin distribution); concepts (eigenvector AHP) are unprotectable methods, referenced, not copied.
* **BSD-3 (scikit-criteria):** compatible but irrelevant (no AHP engine).
* **Unverified licenses (QGIS suitability plugins F–I, provisional):** plugin-page snapshots carry no license field (EasyAHP's GitHub LICENSE was separately verified as GPL-3.0, §14 row E). Provisional rows are treated as All Rights Reserved per M1 precedent — ideas referenced, code not copied, no vendoring.
* **No dependency added** by this task (verified §18 verification: `pyproject.toml` untouched).

---

## 16. Recommended Implementation Specification for M2-T02 (candidate shape — not approved)

The following is a candidate synthesis target for M2-T02, **not an approved contract**. ToolSpec name/version/risk/schema, the `agent → analysis` edge (§13), and output-schema shape require ADR-0008/ADR-0009/ADR-0010 conformance review in T02; QGIS/Processing wiring is explicitly M3; AI assembly of input is explicitly M5.

1. New module `lunar_gis/analysis/ahp.py` (stdlib only; **no `qgis` import** in the math core; placeholder `__init__` docstring updated, not flattened).
2. Public value types (frozen dataclasses): `PairwiseMatrix` (criteria tuple + rows tuple), `AHPWeights` (weights tuple + order), `ConsistencyReport` (lambda_max, CI, RI source/value, CR, threshold, flag), `AHPResult` (weights + report + math provenance + input hash).
3. Functions: `validate_matrix(...) -> None` (raises typed errors per §9 codes), `priority_vector(...) -> tuple`, `consistency(...) -> ConsistencyReport`, `ahp(...) -> AHPResult` (validate → eigenvector → consistency → provenance).
4. Constants: `SAATY_SCALE` (17 values), `SAATY_RI_1980` (n = 1..10), `RI_SOURCE = "saaty-1980"`, `CR_ACCEPT = 0.10`, `CR_TOLERATE = 0.20`, `FLOAT_COMPARE_EPS = 1e-9`, `POWER_TOL = 1e-12`, `POWER_MAX_ITER = 10000`, `RECIPROCITY_TOL = 1e-9`, `SCALE_MEMBERSHIP_TOL = 1e-12` (relative), `MAX_N = 10`, `NUMERICAL_POLICY_VERSION = "1.0"`. Flag strings pinned: `ACCEPTABLE` / `ACCEPTABLE_WITH_WARNING` / `REVISE_REQUIRED`.
5. Later (same or follow-up task, not M2-T01): a `ToolSpec` (candidate name `lunar.ahp.compute_weights`) in `agent/` registry with JSON schema for criteria+matrix, risk ≥ medium (confirmation-gated), executed via `ControlledExecutor`. **Validation split:** JSON Schema validates shape/types/bounds only; all Saaty semantics (exact diagonal, 17-value scale, 1e-9 reciprocity, `INCOMPLETE_MATRIX`, `UNSUPPORTED_MATRIX_SIZE`) live ONLY in `validate_matrix()`; the executor passes engine error codes through verbatim into output/audit. **Governance mapping:** `ConsistencyReport.flag` is part of the output schema; `REVISE_REQUIRED` requires explicit human re-confirmation and surfaces weights + CR + flag + input hash in audit; `ACCEPTABLE_WITH_WARNING` is a flagged success. The ToolSpec accepts n ≥ 1; n < 3 results carry `trivial_consistency: true` (confirmation policy unchanged). QGIS/Processing wiring deferred to M3.
6. Cross-check implementation against AHPy and pymcdm oracles on §14.1 frozen vectors (isolated pinned environment; vendored expected vectors only — never a test-suite import or dependency) before sign-off.
7. T02 must include an explicit executor→engine step-mapping table (executor stage → engine function → error code → audit event), covering: permission check → `validate_matrix()` → confirmation → intent audit → handler → provenance assembly → terminal audit; non-convergence as internal error (audited, never a partial result); no timestamps inside cached results/hashes; 6-decimal display rounding at the output-schema/provenance boundary only.

---

## 17. Open Questions / Deferred Decisions

1. **Hierarchy synthesis** (multi-level composition, distributive vs ideal modes, rank-reversal policy): explicitly M3+; single-matrix engine must not pre-empt the synthesis semantics.
2. **Donegan & Dodd RI (n ≤ 100) adoption** and any `ri_source` flag: deferred; requires its own methodology note if ever adopted.
3. **Geometric-mean estimator** as an optional flagged alternative: deferred; needs a method-selection policy and dual-provenance design first.
4. **Group aggregation** (geometric mean of judgments across experts): deferred to Research Mode (M6).
5. **Sensitivity analysis** (MILESTONES.md M2 lists it): M2-T02 is gated on the core engine only (validate → eigenvector → consistency → provenance + frozen-oracle cross-check). Sensitivity is a separate acceptance item specified as weight-perturbation analysis over the validated engine, with its own determinism/monotonicity criteria, so perturbation logic cannot leak into core `ahp()` purity or the §13 integration boundary.
6. **1×1/2×2 in ToolSpec flows**: decided in §16 item 5 — ToolSpec accepts n ≥ 1; engine marks n < 3 results `ACCEPTABLE` with `trivial_consistency: true`; confirmation policy unchanged.
7. **R `ahp` package review**: deferred as low-relevance to a Python/QGIS runtime.

---

## 18. References

* Saaty, T.L. (1977). A scaling method for priorities in hierarchical structures. *Journal of Mathematical Psychology*, 15(3), 234–281. — Ratio scales from reciprocal matrices; λmax = n for consistent matrices; principal eigenvector solution.
* Saaty, T.L. (1980). *The Analytic Hierarchy Process*. McGraw-Hill. — Fundamental scale; hierarchy; RI table (500-sample simulation).
* Saaty, T.L. (1990). How to make a decision: The Analytic Hierarchy Process. *European Journal of Operational Research*, 48(1), 9–26. — Aw = λmax·w under perturbation; CI = (λmax−n)/(n−1); CR ≤ 0.10 accept, ~0.20 tolerable in some contexts; worked house-buying matrices.
* Saaty, T.L. (1999). The seven pillars of the AHP. ISAHP proceedings. — Reciprocal axiom; principal right eigenvector; homogeneity and 1–9 bound.
* Saaty, T.L. (2001). Deriving the AHP 1–9 scale from first principles. ISAHP proceedings. — Psychophysical derivation of the scale.
* Alonso, J.A. & Lamata, M.T. (2006). Consistency in the analytic hierarchy process: a new approach. *International Journal of Uncertainty, Fuzziness and Knowledge-Based Systems*. — Alternative RI simulation values (noted, not adopted).
* Donegan, H.A. & Dodd, F.J. (1991). A note on Saaty's random indexes. *Mathematical and Computer Modelling*, 15(10), 135–137. — Extended RI set (deferred).
* Crawford, G. & Williams, C. (1985). A note on the analysis of subjective judgment matrices. *Journal of Mathematical Psychology*. — Geometric-mean estimator (deferred alternative).
* Saaty, T.L. (2005). *Theory and Applications of the Analytic Network Process*. RWS, p. 31. — Canonical RI table source tag (`saaty-1980`).
* AHPy v2.1 docs (PhilipGriffith/AHPy, MIT; stars per 2026-09-14 snapshot) — eigenvector+iteration method; dual RI tables; missing-comparison completion (rejected behavior); worked examples as test-oracle source.
* pymcdm release v1.4.0 on PyPI (MIT; SoftwareX DOI 10.1016/j.softx.2023.101368); docs consulted at readthedocs v1.3.0 — eigenvector AHP, 1–9 scale validation, CR < 0.1 gate, λmax = mean((Aw)/w).
* pyDecision (Valdecy/pyDecision, GPL-3.0 LICENSE) — method catalog reference only.
* scikit-criteria (quatrope, BSD-3) — objective weighters; no core pairwise-AHP engine (`ahp_ext/` extra not evaluated).
* plugins.qgis.org: EasyAHP (version record 586 = v1.0.11, QGIS 3.0–3.99; GPL-3.0 per GitHub LICENSE), ahp_application, ahp_analysis, solar_site_suitability (CR < 0.10 gating pattern), planx_suitability_lab (GitLab canonical host; AHP weighting + CR flag per plugin-page description — M3 reference).
* Lunar governance: `AGENTS.md:1-12`; `docs/adr/ADR-0002`; `docs/adr/ADR-0004` (`analysis` row); `docs/architecture/MILESTONES.md` (M2); `.opencode/skills/ahp-mce/SKILL.md` (M2/M3 phase gate); `docs/research/M1-OSS-REUSE-AUDIT.md` (audit format + license precedent).

---

## Verification (M2-T01, research-only)

* `python -m pytest -q` — full suite passes, zero failures (no code changes; exact count verified at gate time)
* `ruff check .`, `ruff format --check .`, `mypy lunar_gis`, `bandit -c pyproject.toml -r lunar_gis`, `python -m build`, `test_qgis_plugin_zip_structure` — all pass
* `git status` shows only `docs/research/M2-AHP-METHODOLOGY-AND-OSS-AUDIT.md` (+ `docs/research/README.md` index line); `pyproject.toml` untouched (no dependency); `lunar_gis/` untouched (no future-milestone code)
