# M3-T04: Deterministic Sensitivity Reporting & Visualization Design

- Status: Design (no implementation)
- Date: 2026-09-18
- Scope: M3-T04 design audit
- Sources of truth: `lunar_gis/analysis/sensitivity.py` (M3-T01),
  `lunar_gis/analysis/sensitivity_tools.py` (M3-T02),
  `lunar_gis/processing/sensitivity_algorithm.py` (M3-T03),
  `docs/research/M2-SENSITIVITY-ANALYSIS-DESIGN.md` (M2-T05, as corrected in
  M3-T03-F1 — M3-T03 follow-up 1: QGIS Processing acceptance-findings
  resolution, commit `41b03f2`)
- Method note: the domain skills named in the task brief (`ahp-mce`,
  `cartography`, `provenance`, `qgis-processing`, `qgis4`, `testing`,
  `technical-documentation`) are not installed in this environment (only
  `customize-opencode` is available, which governs unrelated tooling).
  This design is therefore derived directly from the frozen engine source,
  the accepted M2-T05 design, ADR-0004, and the milestone plan, and is
  submitted to the full specialist-review panel for independent validation.

## 0. Design-only boundary

This document specifies **what** a sensitivity report contains and **how** it
may be presented. It creates no code, no dependencies, no widgets, no charts,
and no Processing outputs. Implementation is deferred:

- Full report generation belongs to **M8** (`lunar_gis/reports`),
  consistent with `M2-SENSITIVITY-ANALYSIS-DESIGN.md` §15
  ("Sensitivity report generation → M8+") and `MILESTONES.md` (M8 Reports +
  Reproducibility).
- Cartographic treatments (print layouts, styled map figures) belong to
  **M7** (`lunar_gis/cartography`), consistent with §15
  ("Tornado diagram visualization → M7+").
- What may exist now without violating scope: the minimal Processing HTML
  summary already produced by M3-T03 (`_build_html`), revised in a future
  task to project the canonical model defined here. That revision is **not**
  part of M3-T04.

## 1. Source of truth and derivation principle

`SensitivityResult` (frozen dataclass, `sensitivity.py:104-122`) is the
**sole analytical source of truth**. The reporting layer defines a derived,
read-only **report view**. The following rules are non-negotiable:

1. **No second source of truth.** The report view carries no independent
   numbers. Every displayed value is traceable to a field of
   `SensitivityResult` (or to `AHPResult` fields already embedded in it via
   provenance).
2. **Three disjoint vocabularies.** Documentation, code, and UI copy must
   distinguish:
   - *mathematical result* — values computed by `sensitivity_ahp()` /
     `ahp()` (weights, rankings, intervals, crossovers, CR, near-ties);
   - *derived presentation* — values computed from the result without new
     mathematics (first-crossover-per-side, display rounding, rank labels);
   - *visual encoding* — how a value is drawn (position, length, text,
     symbol). Visual encoding must never change a value.
3. **Derived values are labeled as derived.** Any number that is not a
   verbatim engine output must be presented with its derivation rule
   (e.g. "first sampled delta below baseline with changed ranking").
4. **Reporting performs no mathematics on matrices.** In particular, the
   reporting layer must never re-run `ahp()`, re-derive weights, recompute
   CR, or re-implement ranking. It reads `SensitivityResult` fields only.
5. **Visualization never alters mathematics.** Choice of chart type, axis
   limits, or rounding affects presentation only and must be documented as
   such (see §2 per-visualization specs).

## 2. Canonical reporting model

The canonical report is a deterministic, JSON-serializable projection of
`SensitivityResult`. Field names below mirror the engine exactly so that
mechanical conformance can be tested later without interpretation.

### 2.1 Required fields

| Report field | Engine source | Notes |
|---|---|---|
| `report_model_version` | constant `"1.0"` (new) | versions this projection, not the math |
| `derived_from_input_hash` | `result.input_hash` | links report to exact engine input |
| `criteria` | `result.criteria` | input order preserved |
| `baseline_weights` | `result.baseline_weights` | full float precision retained |
| `baseline_ranking` | `result.baseline_ranking` | rank 0 = highest weight |
| `criterion_reports` | `result.criterion_results` | one entry per analyzed criterion, target order |
| `method` | `result.method.value` | `"OAT_WEIGHT"` (only supported method) |
| `perturbation_range` | `result.perturbation_range` | requested range (not clamped; see §2.6) |
| `num_steps` | `result.num_steps` | |
| `near_ties` | `result.near_ties` | pairs, input order |
| `sensitivity_policy_version` | `result.sensitivity_policy_version` | note: present in the implementation but absent from the M2-T05 §6.3/§11.1 field lists (M2 defines the constant in §6.1 only) — this design follows the implementation |
| `numerical_policy_version` | `result.numerical_policy_version` | |
| `ranking_policy_version` | `result.ranking_policy_version` | |
| `consistency_policy_version` | `result.consistency_policy_version` | |
| `engine_version` | `result.engine_version` | |

Each `criterion_reports[]` entry carries verbatim:

- `criterion`, `baseline_weight`
- `stability_lower`, `stability_upper` (see §2.7: sample-grid estimates biased outward)
- `crossover_points` (see §5: all sampled deltas with changed ranking)
- `perturbation_values` (per-criterion **clamped** sweep; see §2.6)
- `perturbed_weights`, `perturbed_rankings`
- `consistency_flags`, `consistency_ratios` (see §6: constant under
  OAT_WEIGHT — the report must say so)

### 2.2 Optional fields

- `target_criteria`: present if and only if `result.target_criteria` is not
  `None` (mirrors the existing `_serialize_result` conditional-inclusion
  rule, required by the registry schema validator which lacks nullable
  types). Absence means "all criteria analyzed".
- `presentation_generated_at`: permitted **only** in the presentation
  envelope (see §7.4). Never part of analytical content, never hashed.

### 2.3 Ordering rules

1. `criteria`, `baseline_weights`, `baseline_ranking`: input criteria order.
2. `criterion_reports`: engine emission order, i.e. target-criteria order
   (`None` = input order). Duplicate `target_criteria` entries, if ever
   passed, yield duplicate entries in emission order — the report preserves
   emission order verbatim and must not silently deduplicate or reorder.
   Input-side deduplication is an engine-validation matter for a future
   scoped task, not a reporting rule.
   This matches engine emission order (`sensitivity.py:439-447`).
3. `crossover_points`: ascending delta order **conditional on a valid
   (non-degenerate) sweep** — see §2.6 precondition. The engine scans
   `perturbation_values` in list order (`sensitivity.py:276-289`); list
   order is ascending only when clamping preserves
   `clamped_min < clamped_max`.
4. `near_ties`: engine order (lexicographic by input index;
   `sensitivity.py:149-157`).
5. Report sections (human-readable order, with canonical section keys for
   mechanical conformance): `baseline` → `stability` (per-criterion) →
   `crossovers` → `consistency` → `near_ties` → `provenance`. A conformance
   test asserts section-key sequence, not prose headings.

### 2.4 Deterministic serialization

- JSON object keys sorted (`sort_keys=True`), separators `(",", ":")`,
  UTF-8, `ensure_ascii=False` for criterion names (consistent with
  `_canonical_input_hash` in `ahp.py:230-236`).
- Floats serialized at full `repr` precision in machine artifacts (JSON
  output). Display rounding (§2.5) applies to human-readable text/HTML only
  and must never feed back into data.
- HTML escaping (`html.escape`) for all criterion names and free text,
  as already practiced in `_build_html` — extended to every
  criterion-derived string including `target_criteria` members (see §11
  future task).
- **Field renames are explicit, not mechanical.** The report model renames
  two engine fields for readability: `criterion_results` →
  `criterion_reports`, `input_hash` → `derived_from_input_hash`. All other
  names mirror the engine exactly. A future conformance test must assert
  against the §2.1 table (explicit mapping), never by naive key equality.
- **No report-hash function is defined in M3-T04.** Canonicalization above
  specifies the byte form that the M8 `canonical_report_bytes()` function
  must produce; until M8 defines it (analytical content only, envelope
  excluded, tuple→list normalization for `perturbation_range`/`near_ties`,
  `None`-omission for absent `target_criteria`), "byte-identical report"
  claims are not mechanically testable. §7.2's verification path therefore
  rests on engine-input recomputation, not on a report hash.
- **Envelope boundary (specified, not implemented).** The future envelope
  is `{"analytical": <§2.1 canonical model>, "presentation":
  {"generated_at": <ISO-8601 UTC>}}`. Any hash covers `analytical` only;
  `presentation` is never hashed, never compared.

### 2.5 Numeric display precision

- `DISPLAY_PRECISION = 6` (from `ahp.py:97`) governs all displayed weights,
  deltas, stability bounds, and crossover values in text/HTML/tables.
- Consistency ratios displayed with the exact format `f"{cr:.4f}"`
  alongside the exact flag text; CR thresholds displayed as the exact
  strings `"0.10"`/`"0.20"` with the footnote "classification uses
  `FLOAT_COMPARE_EPS = 1e-9` tolerance on unrounded values". A CR of
  0.1000000005 therefore renders as `0.1000 — ACCEPTABLE`, which is
  mechanically assertable and does not mislead, because the flag (computed
  pre-rounding) is always shown next to the rounded value.
- Step size (grid resolution) displayed per criterion so readers can judge
  crossover approximation quality (see §5 rule 4).

### 2.6 Missing/empty values

- `crossover_points == []` → display "none" plus the sentence "ranking
  unchanged over the sampled sweep". Never display a blank cell.
- `near_ties == []` → omit the near-tie section or state "no near-ties at
  `NEAR_TIE_TOL = 1e-6`". Never imply ties were not checked.
- `target_criteria` absent → display "all criteria".
- `perturbation_values` are **clamped per criterion** to the valid weight
  range (`sensitivity.py:205-221`): each criterion's sweep differs. The
  report must show the effective (clamped) sweep per criterion next to the
  requested range, so readers do not misread cross-criterion comparisons.
- **Sweep-validity precondition.** Clamping intersects the requested range
  with `[-w_k + eps, 1 - w_k - eps]` per criterion. If the requested range
  does not intersect a criterion's valid range (e.g. high-weight criterion
  with a large positive requested range), clamping inverts
  (`clamped_min > clamped_max`) and the engine emits a descending,
  degenerate sweep on which §2.3.3 and the stability-scan assumptions do
  not hold. The report model therefore **requires** a non-degenerate sweep
  (`effective_min < effective_max`) as a precondition; degenerate sweeps
  are an engine input-validation gap for a future scoped task (reject or
  skip with explicit record — design choice deferred, implementation
  forbidden here), and no report may present a degenerate sweep as valid.

### 2.7 Stability bounds are sample-grid estimates biased outward

`stability_lower`/`stability_upper` are computed by
`_compute_stability_interval` (`sensitivity.py:224-273`), which scans each
side **from the sweep edge toward zero** and stops at the first (outermost)
unstable sample:

- If the outermost sample on a side is stable, the bound is the sweep edge
  (full range retained on that side).
- If the outermost sample is unstable, the bound falls back to the adjacent
  sample value (`delta ± step_size`, `sensitivity.py:254,269`) — a sampled
  point, **not** a midpoint between samples.
- The midpoint branch (`(prev + delta) / 2`, lines 252, 267) requires an
  interior transition with a stable predecessor. Under exact OAT weight
  monotonicity (perturbed target weight strictly increasing, others strictly
  decreasing, non-target ratios preserved) each side's attainable pattern is
  `[changed…changed, stable…stable, baseline, …]`, so an existing
  instability always reaches the sweep edge and the edge fallback applies.
  The midpoint branch is reachable only via tolerance-edge flicker, not in
  the normal case.

Consequences for reporting (this corrects the "conservative midpoint"
wording of the initial M3-T04 draft, which repeated the code comment's
intent without verifying scan direction):

1. Bounds are **sample-grid estimates biased outward** (toward wider
   intervals), never exact analytical roots. They must be labeled
   "estimated stability bounds (sample-grid estimate, biased outward by up
   to one grid step or more)" with the per-criterion step size shown.
2. The word "conservative" must not be used: in the reachable case the
   estimate overstates stability.
3. V3 bars (§3) therefore show grid estimates, and §5.4's rule (true
   crossing lies between samples) applies to bound interpretation as well.
4. A future engine task (out of M3-T04 scope; implementation forbidden
   here) may re-specify the scan outward-from-zero for the innermost
   transition to obtain genuinely conservative bounds; such a change bumps
   the numerical/sensitivity policy versions and is recorded under §7.3.

### 2.8 Unsupported methods

`OAT_PAIRWISE` (and any unknown method string) raises `SensitivityError`
before any result exists. **There is no report for an unsupported method** —
only the engine error path (tool error / `QgsProcessingException`). The
report model must not define placeholder, partial, or "upcoming method"
sections.

### 2.9 REVISE_REQUIRED and near-ties in the model

- Steps flagged `REVISE_REQUIRED` are included with their flag; exclusion
  is forbidden (M2-T05 §9; §6 below).
- Near-tie pairs are listed verbatim with the tolerance constant shown.
  Near-tie status is baseline metadata, not a ranking override (see §4 rule 3).

### 2.10 Provenance fields

See §7. The report model carries all five policy versions plus method,
range, steps, target criteria (when set), engine version, and input hash.

## 3. Stability visualizations

All visualizations below consume **only** report-model fields. Each entry
specifies placement: file-backed Processing HTML output (the correct QGIS 4
delivery vehicle — see §8.3), future QGIS panel (needs a M7+/M8 task), or
both.

> QGIS API note (qgis-expert review): `QgsProcessingOutputString`
> (`outputString`) is a plain-string output — an HTML string returned
> through it is displayed as text in the results panel, subject to string
> truncation, and inline `<svg>` never renders. That is the current M3-T03
> state (`sensitivity_algorithm.py:168-169`: `OUTPUT_RESULT_HTML` is a
> `QgsProcessingOutputString`). The sound QGIS 4 pattern is
> `QgsProcessingParameterFileDestination` (extension `html`) +
> `QgsProcessingOutputHtml`, writing a temp `.html` file containing tables
> and inline SVG. Migrating the output type is a **breaking change**
> requiring its own scoped migration task (see §11) — it is not a drop-in
> projection of the §2 model.

### V1. Stability summary table (canonical, required)

- **Communicates:** baseline weight, estimated stability interval, crossover
  count, consistency flag, and near-tie membership per criterion — the
  complete decision-relevant summary in one place.
- **Input data:** `criterion`, `baseline_weight`, `stability_lower`,
  `stability_upper`, `len(crossover_points)`, baseline consistency flag,
  `near_ties` membership.
- **Semantics/ordering:** one row per analyzed criterion in report order;
  columns: Criterion | Baseline weight (6dp) | Stability interval
  `[lower, upper]` (6dp, labeled "estimated") | Crossovers (count + first
  below/above, 6dp, or "none") | Consistency | Near-tie (yes/no).
- **Ties/precision:** weights at 6dp; tied criteria show equal rank in a
  Rank column; near-tied pairs marked with `≈` plus footnote giving
  `NEAR_TIE_TOL`. The Consistency column repeats the single baseline flag
  for every row and is headed "Consistency (baseline, global)" so readers
  do not infer per-criterion variation (§6 rule 2).
- **Accessibility:** this table is the **accessible fallback for every
  chart** (V2–V4). Screen-reader-first: `<caption>`, `<th scope>`, no
  color-only meaning.
- **Placement:** Processing HTML (now/future revision, file-backed per
  §8.3) and future panel.

### V2. Weight-vs-delta line chart (per analyzed criterion)

- **Communicates:** how every criterion's weight moves as one criterion is
  perturbed; crossings are visible as line intersections.
- **Input data:** `perturbation_values` (x), `perturbed_weights` columns (y
  series, one per criterion), `baseline_weight` (marker at δ=0),
  `stability_lower`/`stability_upper` (shaded-or-hatched band edges drawn
  as lines, not color-only fills).
- **x/y semantics:** x = absolute weight offset δ applied to the perturbed
  criterion (per-criterion clamped range shown on the axis; ranges differ
  across charts — each chart titles its own sweep range). y = criterion
  weight in [0, 1].
- **Ordering:** series order = input criteria order; perturbed criterion
  drawn with distinct marker shape plus direct label.
- **Tie handling:** intersections within `FLOAT_COMPARE_EPS` are ties, not
  crossings; chart annotation must say "apparent intersections are subject
  to 1e-9 tie tolerance — see table V1".
- **Precision:** axis ticks at 6dp-capable scale; sample points drawn as
  markers (data are samples, not a continuous curve — **markers mandatory,
  line segments labeled "linear interpolation between samples"** or use
  step rendering; never imply an analytical curve).
- **Accessibility:** every line gets a distinct dash pattern **and** direct
  label; V1 table adjacent; title names the perturbed criterion.
- **Placement:** both (file-backed HTML per §8.3; native redraw in future
  panel). Rendering must be dependency-free (deterministic
  inline SVG generated from stdlib data — no matplotlib runtime; see §10).
  SVG text elements carry `<title>` for screen readers.

### V3. Stability-interval strip plot (all criteria, one figure)

- **Communicates:** comparative robustness — which criteria tolerate large
  perturbations before any rank change.
- **Input data:** per criterion: clamped sweep `[min, max]`,
  `[stability_lower, stability_upper]`, first crossover below/above (derived,
  labeled).
- **Semantics:** one horizontal row per criterion (report order); x = δ.
  Row shows: full sampled sweep (thin line), estimated stability interval
  (thick bar with end-tick marks), crossover ticks (one tick per sampled
  crossover delta), δ=0 marker (baseline).
- **Ordering/ties:** rows in report order; numeric interval labels at 6dp
  on each bar (no color-only reading).
- **Precision/accessibility:** end-tick marks + numeric labels make the
  interval readable without color; caption states sample-grid estimation
  biased outward (§2.7) and per-row clamped ranges.
- **Placement:** both (file-backed HTML per §8.3; native redraw in future panel).

### V4. Rank-step plot (per analyzed criterion)

- **Communicates:** exactly when and how the ranking vector changes along
  the sweep — the discrete counterpart of V2.
- **Input data:** `perturbation_values` (x), `perturbed_rankings` (y, one
  step series per criterion showing that criterion's rank), baseline
  ranking (reference), crossover deltas (event ticks).
- **Semantics:** x = δ; y = rank integer (0 = best, inverted axis so rank 0
  is at top). Step (zero-order-hold) rendering — rank is piecewise constant
  between samples by construction of the comparison rule, but the true
  transition lies in the interval between two samples (§5.4): step edges
  are therefore drawn **at sample locations and annotated as grid
  artifacts** ("edge at sampled δ; true transition in adjacent interval"),
  exactly like V2's interpolation disclaimer. Never imply knowledge of the
  transition point between samples.
- **Ties:** equal ranks shown as overlapping steps with shared label
  ("tied at rank r"); no jitter, no artificial separation.
- **Precision/accessibility:** y-axis integer ticks with "Rank 0 = highest
  weight" label; event table (delta → ranking vector) adjacent as text.
- **Placement:** both (file-backed HTML per §8.3 with adjacent event
  table; native redraw in future panel).

### Rejected alternatives (with reasons)

- **Tornado diagram:** deferred to M7+ by §15. Although tornado charts are
  an established OAT summary (sorted impact widths), they collapse discrete
  ranking events into interval widths and would hide the crossover/consistency
  content that is this report's analytical core. Revisit only in M7
  cartography scope and only with event-preserving augmentation.
- **Pie/donut of weights:** angle/area perception is poor for close weights
  and actively harmful near ties; tables + V2 dominate it. Rejected.
- **Color-only heatmap of perturbed weights:** fails accessibility (§9)
  and hides the discrete ranking events that are the actual analytical
  content. Rejected as primary view (a labeled matrix table is acceptable
  as an appendix view in M8).
- **Continuous-curve rendering of V2 without sample markers:** implies an
  analytical weight function the engine does not provide (engine stores
  samples). Rejected; markers mandatory.
- **Monte Carlo bands / confidence shading:** nondeterministic content is
  excluded by M2-T05 §10.5. Rejected.
- **3D surfaces:** no analytical third dimension exists in OAT sweeps;
  decorative. Rejected.

## 4. Ranking representation

1. **Rank integers are displayed verbatim** from `baseline_ranking` /
   `perturbed_rankings`. Rank 0 = highest weight (best).
2. **Ties share a rank.** The engine counts `weights[j] > weights[i] +
   FLOAT_COMPARE_EPS` as strictly-above, so two weights with
   `|wᵢ − wⱼ| ≤ FLOAT_COMPARE_EPS (1e-9)` receive the same rank; the engine
   performs no tie-breaking (`sensitivity.py:130-146`), and neither may the
   report. Display tied criteria grouped (e.g. "Rank 1: B, C (tied)").
3. **Near-ties are annotations, not ranking changes.** A pair in
   `near_ties` (`|Δw| < NEAR_TIE_TOL = 1e-6`) keeps its computed ranks; the
   report marks the pair with `≈` and the tolerance value. A near-tie must
   never be rendered as a tie.
4. **Rank-change statements** compare integer vectors with
   `_rankings_equal` semantics: any element-wise difference is a change.
   Human-readable form names the event ("at δ = −0.120000, B moves above
   A; ranking [0,1,2] → [1,0,2]") and always shows both vectors.
5. **No alternative ranking policy.** Median-rank, fractional-rank, or
   random-tie-break presentations are forbidden — they would contradict
   `RANKING_POLICY_VERSION = "1.0"`.

## 5. Crossover representation

Engine fact: `crossover_points` lists **every sampled delta whose ranking
differs from baseline** (`sensitivity.py:276-289`). It is not a list of
pairwise crossings. Presentation rules:

1. **Report the raw list** (ascending, 6dp) as the evidence base.
2. **Derived headline values** permitted, each labeled derived:
   - *first crossover below baseline*: min sampled δ < 0 with changed
     ranking ("first observed", not "the crossing");
   - *first crossover above baseline*: symmetric;
   - *crossover count*: number of changed samples (a density signal, not a
     count of distinct pairwise crossings).
3. **Multiple crossings** are listed individually; the report must not
   collapse them into one ("3 sampled crossovers below baseline" with the
   values).
4. **Approximation honesty:** the true crossing lies between two samples;
   grid resolution = per-criterion step size, displayed next to every
   crossover claim. Stability bounds are likewise grid estimates (§2.7);
   crossover deltas are sample locations, not roots.
5. **Boundary cases:** a changed sample at the sweep edge is reported as
   "ranking changed at sweep boundary δ = X (range-truncated; behavior
   beyond the sweep is unknown)". Never extrapolate.
6. **Outside the perturbation range:** no claim. If no sample changed,
   report "no sampled crossover in [min, max]" — never "no crossover
   exists".
7. **Tolerance ties:** samples whose ranking equals baseline are stable
   points even if weights are within eps — equality of the integer vector
   is the criterion, not weight distance.
8. **Crossover ⇒ ranking change, by definition.** Every listed crossover
   corresponds to a changed integer ranking vector; the report shows the
   changed vector for the first below/above cases.

## 6. Consistency communication

Engine fact (OAT_WEIGHT): per-step `consistency_flags`/`consistency_ratios`
repeat the **baseline** matrix consistency (`sensitivity.py:461-466`).
Weight perturbation does not re-run AHP on a new matrix, so there is no
per-step CR recomputation. The report must present consistency truthfully:

1. **Single baseline consistency block**: CR value, flag, and the exact
   classification rule —
   - `ACCEPTABLE`: CR ≤ 0.10 + 1e-9 (n ≥ 3);
   - `ACCEPTABLE_WITH_WARNING`: 0.10 + 1e-9 < CR ≤ 0.20 + 1e-9;
   - `REVISE_REQUIRED`: CR > 0.20 + 1e-9;
   - n < 3: always `ACCEPTABLE`, `trivial_consistency = true`
   (thresholds from `ahp.py:21-25`, `86-87`).
2. **Step series labeled as constant-by-construction** under OAT_WEIGHT:
   "consistency shown per step for schema uniformity; all steps carry the
   baseline CR = X (flag Y) because OAT weight perturbation does not alter
   the pairwise matrix." This corrects the aspirational per-step language
   in M2-T05 §9 for the implemented method while preserving its
   report-but-flag decision for any future pairwise method.
3. **REVISE_REQUIRED is never hidden or excluded.** A baseline matrix with
   `REVISE_REQUIRED` still yields a full sensitivity report (engine
   computes it), headed by a prominent, text-first warning: results
   describe an inconsistent judgment set and rankings are not decision
   grade. Color (if any) is redundant with the text.
4. **Per-step display** (tables/V4 event lists) shows flag + CR at every
   step — repetition is intentional evidence, not noise.
5. **Future OAT_PAIRWISE**: if ever implemented, per-step CR genuinely
   varies and this section's rule 2 is superseded by a separately scoped
   design update. M3-T04 does not design pairwise reporting beyond
   preserving the report-but-flag principle.

## 7. Provenance and reproducibility

### 7.1 Required provenance block (every report)

Method, all five policy versions (`sensitivity`, `numerical`, `ranking`,
`consistency`, plus `engine_version`), `input_hash` (full SHA-256 in JSON;
truncated `…` display with full value in `<code>`/appendix in HTML),
requested `perturbation_range`, `num_steps`, effective per-criterion clamped
sweeps, `target_criteria` (or "all"), `report_model_version = "1.0"`, and
the derivation statement: "analytical content = `SensitivityResult`
`{input_hash}`; presentation derived without new mathematics."

### 7.2 Reproducibility contract

Identical `{criteria, matrix, method, perturbation_range, num_steps,
target_criteria}` on the same engine and policy versions → byte-identical
analytical content (engine determinism, M2-T05 §10; no RNG, no I/O, no
timestamps in math results per `ahp.py:27`). The report model adds no
entropy: ordering (§2.3) and serialization (§2.4) are fully specified.
Version qualification is required: the same user inputs on bumped
`numerical`/`ranking`/`sensitivity`/`consistency` policy versions may
diverge, so a reproducibility claim always names the five policy versions
plus `engine_version` (§7.1 block).

**Input-hash scope (correction to the initial M3-T04 draft).**
`SensitivityResult.input_hash` binds **only `{criteria, matrix}`**
(`ahp.py:230-236` payload, propagated verbatim at `sensitivity.py:502`). It
does **not** bind `method`, `perturbation_range`, `num_steps`, or
`target_criteria`: two sweeps over the same matrix with different ranges
share one hash with different analytical content. The verification path is
therefore two-part, and the report must present both:

1. recompute the matrix hash from `{criteria, matrix}` (SHA-256 canonical
   JSON) and compare with `derived_from_input_hash` — verifies the matrix;
2. equality-check the sweep parameters (`method`, `perturbation_range`,
   `num_steps`, `target_criteria`) and all five policy versions against the
   report's provenance block — verifies the sweep.

A recompute-from-full-sensitivity-inputs will never match the engine hash
by construction; the report must never instruct that comparison. M8 may
additionally define a `sensitivity_params_hash` (canonical JSON of the
sweep parameters + policy versions) as a single-comparison upgrade; until
then, the two-part path above is normative.

### 7.3 Version-change policy

Any change to derivation rules (new report field, headline-crossover
definition change, rounding change, ordering change, wording change that
alters an asserted fixture string) bumps `report_model_version`
independently of engine policy versions. Engine policy bumps do not change
the report model unless a derivation rule changes.

Version semantics: `MAJOR.MINOR` — MAJOR for field additions/removals or
derivation-rule changes (old readers must refuse); MINOR for clarifications
that do not alter asserted values (prose, captions). Reader rule: a reader
accepts `report_model_version` if and only if MAJOR equals its supported
MAJOR. The initial version `"1.0"` in §2.1 follows this scheme.

### 7.4 Generation timestamp

Permitted **only** in the presentation envelope (e.g. HTML footer:
"rendered <ISO-8601 UTC>"), explicitly labeled "presentation metadata —
excluded from analytical content and from any hash". Rationale recorded:
operators need to distinguish report renders in long-lived projects;
analytical reproducibility is unaffected because the timestamp never enters
`SensitivityResult` or the canonical model.

## 8. QGIS integration boundary

```
analysis (pure math, stdlib, no QGIS)
   │  SensitivityResult
   ▼
reporting (pure view derivation, stdlib, no QGIS, no network, no AI)
   │  canonical report model (JSON-serializable dict)
   ▼
processing (thin adapter: parse JSON → engine → serialize → present)
   │  OUTPUT_RESULT (JSON) + OUTPUT_RESULT_HTML (HTML)
   ▼
ui (future panel: renders report model; performs no mathematics)
```

1. **Analysis stays pure.** `sensitivity.py` gains no reporting imports;
   its public API is unchanged by this design.
2. **Reporting is QGIS-free.** The future reporting code (M8,
   `lunar_gis/reports/sensitivity.py`) imports `analysis` types for reading
   only and must remain importable and testable without a QGIS runtime —
   this directly resolves the M3-T03-F1 testing limitation (M3-T03
   follow-up 1: QGIS Processing acceptance-findings resolution, commit
   `41b03f2`), where `_serialize_result`/`_build_html` are untestable only
   because they live in a QGIS-importing module. The canonical model and
   its derivation functions must live outside `lunar_gis/processing/`.
   **Narrowed import rule (qgis-expert review):** ADR-0004 permits `reports`
   to import `project`, but `project` imports `qgis.core`, so a literal
   reading would reintroduce QGIS transitively. `reports/sensitivity.py`
   is therefore restricted to **stdlib + `lunar_gis.analysis` (+
   `lunar_gis.utils` / `lunar_gis.provenance` only if QGIS-free at use
   time); it MUST NOT import `project`, `qgis.core`, `qgis.PyQt`, `agent`,
   `ai`, `data`, `cartography`, or any network client. M8 must add an
   import-guard test (import `lunar_gis.reports` without QGIS on
   `sys.path` minus QGIS + a static `grep` for `import qgis` under
   `lunar_gis/reports/`) so the QGIS-free property cannot regress.
3. **Processing stays thin.** The algorithm keeps its JSON-parse →
   `sensitivity_ahp()` → serialize shape but adds no mathematics, no
   progress/cancellation coupling (engine remains atomic, M3-T03 decision
   stands). A future revision projects the canonical model into HTML
   **through the file-backed pattern** (`QgsProcessingParameterFileDestination`
   + `QgsProcessingOutputHtml`, §3 note) — a breaking output-type migration
   from today's `QgsProcessingOutputString`, requiring its own scoped
   migration task. No new outputs beyond the migrated pair without a
   scoped task.
4. **UI performs no GIS mathematics.** A future panel renders V1–V4 from
   the report model (tables natively; SVG inline); any recomputation from
   matrices re-enters through the engine, never through view code.
5. **No AI/network dependency.** Reports render fully offline (AGENTS.md:11).
   No external tiles, fonts, CDNs, or model calls in the rendering path.

### ADR decision

**No new ADR is created in M3-T04.** ADR-0004 already assigns
`reports` = "reproducible reports, markdown/html/pdf" with allowed imports
`provenance, analysis, project, utils`, and `processing/` as the thin
algorithm host. This design uses exactly those boundaries; it changes no
responsibility and no dependency direction. If a future implementation task
discovers a boundary conflict (e.g. panel needs state the DAG forbids), an
ADR update is required then — recorded here as an explicit trigger, not a
preemptive ADR.

## 9. Accessibility and usability requirements

1. **V1 table is mandatory** alongside every chart; charts are never the
   sole carrier of a result.
2. **No color-only encoding.** Series distinguished by dash pattern +
   direct labels; intervals by end-ticks + numeric labels; flags by text.
3. **Screen-reader HTML:** `<caption>`, `<th scope="col|row">`, chart
   `<svg role="img">` with `<title>`/`<desc>`, data tables adjacent, no
   information in CSS pseudo-content.
4. **Titles and axes:** every figure has a title naming the perturbed
   criterion and sweep range; x-axis "perturbation δ (absolute weight
   offset)"; y-axes "weight" / "rank (0 = highest)".
5. **Precision sufficiency:** 6dp display (§2.5) so close weights and narrow
   intervals remain distinguishable in text form.
6. **No gradients or decorative styling.** Flat, high-contrast, print-safe
   rendering consistent with QGIS Processing HTML output constraints.
7. **Criterion-name safety:** escaping, full UTF-8 support, long-name
   wrapping rules (no truncation without ellipsis + full name in title
   attribute).

## 10. OSS/reuse audit (reporting & visualization)

Scope: libraries/approaches usable for deterministic sensitivity reporting
without violating stdlib-only analysis, offline operation, or GPL-2.0-or-later
compatibility. **No dependency is added in M3-T04**; verdicts below are
design guidance for future implementation tasks.

| Candidate | Project / repo | License (verified) | Relevant function | Verdict |
|---|---|---|---|---|
| Inline SVG (stdlib f-strings) | — (technique, no project) | n/a | deterministic line/step/strip charts in HTML | **ADOPT (technique)** — zero dependencies, byte-deterministic output, screen-reader `<title>` support, works in file-backed Processing HTML (§8.3) + future panel |
| HTML tables (stdlib `html.escape`) | — (technique) | n/a | V1 + event lists, accessible fallback | **ADOPT (technique)** — already proven in `_build_html` |
| Qt rich text (`QTextDocument`) / QGIS HTML outputs | Qt / QGIS (already required runtime) | LGPL-3 / GPL-2+ (runtime env) | render report HTML in panel/help | **ACCEPTABLE (runtime only)** — no new dependency; presentation only |
| matplotlib | matplotlib.org / github.com/matplotlib/matplotlib | PSF-based, BSD-compatible (verified 2026-09-18) | publication charts | **REJECT (runtime)** — heavy dependency stack (numpy, pillow, fontconfig), platform font-rendering nondeterminism breaks byte-reproducibility, overkill for line/step charts; **REFERENCE-ONLY** for chart-design conventions |
| plotly / any CDN-JS charting | plotly.com | MIT (library) but delivery is the issue | interactive charts | **REJECT** — CDN/JS delivery violates offline rule (AGENTS.md:11); interactive zoom invites misreading sampled data as continuous; supply-chain weight unjustified |
| pandas / numpy reporting frames | — | BSD-3 | tabular manipulation | **REJECT** — analysis is stdlib-only by frozen policy; reporting must not introduce the numerical stack the engine deliberately avoids |
| QGIS native layout/cartography (M7) | QGIS / `lunar_gis/cartography` | GPL-2+ | print-grade figures | **DEFER to M7** — correct home for styled map-adjacent figures; out of M3 scope |
| tabulate / prettytable et al. | various (MIT/BSD) | permissive | text tables | **REJECT** — stdlib formatting suffices; each micro-dependency is unjustified supply-chain surface |

Security/supply-chain note: the ADOPT rows add zero supply-chain surface
(stdlib techniques). The ACCEPTABLE row uses the already-required QGIS/Qt
runtime. All REJECT rows are rejected on architecture/determinism grounds
independently of their (mostly permissive) licenses, so no license
obligation is incurred. Per AGENTS.md:12, no external code is copied.

## 11. Deferred items and milestone mapping

- M7: styled/cartographic figures, tornado-style comparative views (only if
  a multi-factor method ever exists), print layouts.
- M8: full report generation module (`lunar_gis/reports/sensitivity.py`
  under the §8.2 narrowed import rule + import-guard test), report-model
  conformance tests (ordering §2.3 incl. section keys, serialization §2.4,
  two-part verification §7.2, exact CR format §2.5, sweep-validity
  precondition §2.6), `canonical_report_bytes()` definition,
  optional `sensitivity_params_hash`, workflow packaging of reports.
- Future scoped migration task (not M3-T04): migrate `OUTPUT_RESULT_HTML`
  from `QgsProcessingOutputString` to `QgsProcessingOutputHtml` +
  `QgsProcessingParameterFileDestination` (breaking output-type change, §3
  note), project the §2 canonical model (consistency-constant labeling,
  clamped-sweep display, V1 table columns incl. Rank/Consistency/Near-tie,
  "estimated" labels, step sizes, provenance block completion with all five
  policy versions + `report_model_version` + derivation statement), fix
  crossovers to 6dp, add `<caption>`/`<th scope>` + `NEAR_TIE_TOL` footnote,
  full-value input hash, and `html.escape` every criterion-derived string
  including `target_criteria` members (XSS hardening for the local Results
  viewer; current `sensitivity_algorithm.py:360` interpolates the list
  unescaped).
- Future scoped task: OAT_PAIRWISE would require a reporting addendum (§6
  rule 5 trigger); nothing in this design presupposes it.
- Future scoped task: degenerate-sweep input validation (reject or
  explicitly recorded skip; §2.6 precondition).

## 12. References

1. M2-T05 design: `docs/research/M2-SENSITIVITY-ANALYSIS-DESIGN.md` (§§6–11
   engine contract; §13 OSS audit; §15 deferrals).
2. Engine: `lunar_gis/analysis/sensitivity.py` — ranking
   (`_compute_ranking`, `FLOAT_COMPARE_EPS`), near-ties (`NEAR_TIE_TOL`),
   clamping (`_clamp_perturbation_range`), stability estimation
   (`_compute_stability_interval`), crossover scan (`_detect_crossovers`),
   baseline-constant consistency (lines 461–466).
3. AHP engine: `lunar_gis/analysis/ahp.py` — `DISPLAY_PRECISION`,
   consistency thresholds, `_canonical_input_hash`, no-timestamp guarantee.
4. ADR-0004 module boundaries; MILESTONES.md (M7/M8); AGENTS.md:1,2,11,12.
5. Triantaphyllou & Sánchez (1997); Pankratova & Nedashkovskaya (2016);
   Więckowski et al. (2024, PySensMCDA) — per M2-T05 §17.
