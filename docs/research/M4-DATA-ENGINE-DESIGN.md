# M4-T01: Data Engine Architecture, Methodology & OSS Audit

- Status: Design accepted (M4-T01); partially implemented by M4-T02
  (`lunar_gis/data/contracts.py` + `discovery_qgis.py`: contracts,
  classification v1, discovery snapshot — see §18)
- Date: 2026-09-18
- Scope: M4-T01 research/design audit
- Sources of truth: `AGENTS.md` (12 rules), ADR-0001…ADR-0012,
  `docs/providers/PROVIDER_CONTRACT.md` (conceptual sketch),
  `docs/security/SECURITY_MODEL.md`, `docs/research/M1-OSS-REUSE-AUDIT.md`
  (§§12–16, 21, 23 provider findings),
  `lunar_gis/agent/{registry,governance,execution}.py` (M1 tool boundary),
  `lunar_gis/project/context.py` (`LayerSummary`/`ProjectContext`),
  `lunar_gis/analysis/*` (deterministic-engine precedent: pure math +
  frozen dataclasses + provenance).
- Method note: the domain skills named in the task brief (`geospatial-data`,
  `stac`, `osm`, `qgis-plugin-development`, `pyqgis`, `qgis4`,
  `qgis-processing`, `provenance`, `security`, `testing`,
  `technical-documentation`, `ai-tool-calling`) are not installed in this
  environment (only `customize-opencode` is available, which governs
  unrelated tooling). This design is therefore derived directly from the
  frozen sources above and is submitted to the full 8-reviewer specialist
  panel for independent validation.

## 0. Design-only boundary

This document specifies **what** the Data Engine is, what contracts it
freezes, and what stays deferred. It creates no classes, no adapters, no
downloads, no STAC/OSM integration, no AI integration, no Processing
algorithms, no transformations, and no dependencies. The governing
principle (AGENTS.md:5,6,11; ADR-0003) is:

> Local/project data is preferred; external data is controlled; the AI
> must never directly fetch arbitrary URLs or manipulate arbitrary files.

Enforcement path (never advisory): `request → validated provider/tool →
governed execution → provenance` (AGENTS.md:3; ADR-0002; ADR-0010).

## 1. Data Engine architecture

### 1.1 Refined boundary

```text
QGIS Project / Local Files
          │
          ▼
  Data Discovery (read-only QGIS queries → LayerInventory)
          │
          ▼
  DataRequirement (structured, versioned contract)
          │
          ▼
AVAILABLE / DERIVABLE / MISSING  (deterministic predicate, LLM never authority)
          │
          ├───────────────────┐
          │                   │
   Local/Project         Controlled
    Fulfillment          Providers
   (layer reference)    (allowlisted adapters)
          │                   │
          └────────┬──────────┘
                   ▼
             Validation (QGIS/GDAL authority)
                   │
                   ▼
     Transformation (explicit steps, QGIS/Processing executes,
                     Data Engine records — never computes)
                   │
                   ▼
              Provenance (min record §10, secrets redacted)
                   │
                   ▼
              DataResult (layer reference or sandbox file + provenance)
```

Refinements vs the illustrative sketch in the task brief: (a) Discovery
emits a `LayerInventory` snapshot distinct from live QGIS objects; (b)
fulfillment splits into reference (local) vs acquisition (provider) paths
before validation converges them; (c) transformation is record-only in the
Data Engine; (d) every stage emits provenance, not just the end.

### 1.2 Module placement (ADR-0004 as amended by ADR-0012)

- `lunar_gis/data/` owns: discovery snapshot builders, requirement
  contract, classification predicate, adapter interface + registry,
  validation orchestration (calling QGIS/GDAL, not reimplementing checks),
  transformation-step records, provenance-shape definition + record
  emission, sandbox path policy.
- Ownership split (no duplication): `data` defines the `DataProvenance
  v1.0` shape and emits records; `provenance` stores/audits them. `data`
  MUST NOT reimplement the audit store.
- `lunar_gis/data/` MUST NOT import: `agent` (tools wrap data ops, not
  vice versa), `ai`, `cartography`, `reports` (reports consume
  `DataResult`s downstream), `qgis.gui`/`qgis.PyQt`, or network clients
  directly (egress only inside adapter transport under §5.2/§9 wrapper).
- `lunar_gis/data/` MAY import: `provenance`, `utils`, `qgis.core`/
  Processing (GIS authority, AGENTS.md:1).
- Narrowed rule (M3-T03-F1 lesson — M3-T03 follow-up 1: helpers
  untestable because they lived in a QGIS-importing module; commit
  `41b03f2`): `lunar_gis/data/`
  MUST NOT import `project` in pure-contract modules, because `project`
  transitively reintroduces QGIS. Frozen file split:
  - `lunar_gis/data/contracts.py` — requirement, inventory/provenance
    shapes, classification predicate, sandbox policy. Allowed imports:
    stdlib + `lunar_gis.utils` + `lunar_gis.provenance` (only if QGIS-free
    at use time). No `project`, no `qgis.*`, no network.
  - `lunar_gis/data/discovery_qgis.py`, `validation_qgis.py`,
    `adapters/` — live-QGIS code, main-thread only (see below).
- Import-guard tests (mandatory at implementation, M8-style precedent
  from M3-T04 §8.2): import `lunar_gis.data.contracts` with QGIS blocked
  on `sys.path` + static `grep` ban on `import qgis` under
  `lunar_gis/data/contracts.py`, so the QGIS-free property cannot regress
  on a first convenience import.
- **Main-thread rule.** All live `QgsProject` / `QgsMapLayer` / `QgsField`
  access (discovery getters, validation probe layers, transformation
  inputs) happens on the main/GUI thread — QGIS object lifetime and SIP
  wrappers are not thread-safe. Off-thread work receives detached
  snapshots/records only, never live layer objects.

### 1.3 No second source of truth

`LayerInventory` snapshots and `DataResult` provenance describe QGIS
reality; they never replace it. Snapshot rules (frozen):

- `LayerInventory` is an ordered list sorted by `layer_id`
  (deterministic; QGIS `mapLayers()` dict order is not a stability
  contract). No sorting/dedup surprises: evidence preserves inventory
  order verbatim.
- Fields: `snapshot_id` (sha256 of ordered layer_ids + `taken_at`),
  `taken_at` (ISO-8601 UTC), `project_dirty` (`QgsProject.isDirty()` at
  snapshot time), `total_count`, `truncated: bool`.
- Invalidation: any project dirty-flag transition or layer add/remove
  after `taken_at` marks the snapshot stale → must re-snapshot before
  classification/validation. Tool outputs and UI render `snapshot
  taken_at + stale warning`; a snapshot must never be presented as live
  state.

## 2. Project/local data discovery

### 2.1 Inventory snapshot

Discovery builds a `LayerInventory`: one `LayerRecord` per project layer,
extending the existing `LayerSummary` (`context.py`: layer_id, name,
provider, geometry_type?, crs_authid?, feature_count?) with:

- `extent` (xmin, ymin, xmax, ymax + CRS authid of the extent) — may be
  `None` if the provider cannot supply it without a full scan;
- `fields`: list of `{name, type}` for vector layers — may be `None` for
  raster/mesh or when the provider defers schema;
- `source`: provider connection string **redacted** (credentials stripped
  per AGENTS.md:10; `utils` redaction);
- `storage`: enum `memory | file | database | remote-service | unknown`,
  plus `reachable: KNOWN-REACHABLE | KNOWN-UNREACHABLE | UNKNOWN` (a
  remote-service layer that fails a cheap open check is
  `storage=remote-service, reachable=KNOWN-UNREACHABLE` — never folded
  into one overloaded value);
- `temporal`: `{has_time: bool}` only (no temporal modeling in M4);
- `valid`: QGIS layer `isValid()` (layer opened — NOT per-feature geometry
  validity, see §7 item 7, Geometry validity) at snapshot time.

Non-goals for M4: mesh layers beyond identification, temporal ranges,
relationship (join) inference, statistics beyond counts.

### 2.2 Unknown is a first-class value

Following the existing defensive pattern in `context.py` (try/except →
`None`) and the M1-audit risk note (`featureCount() == -1` means unknown,
not zero). Every nullable discovery field carries a three-state
representation — `KNOWN(value)` / `UNKNOWN` (provider returned
unknown, e.g. count `-1`) / `UNAVAILABLE(reason)` (lookup failed or
deferred) — so classification (§3) can distinguish `coverage-gap` from
`unknown-deferred`:

- `feature_count == -1` MUST be recorded as `UNKNOWN`, never `0`.
- CRS: `crs().authid()` returns `""` (not an exception) when unknown —
  normalize `""` → `crs_authid = None` + `crs_known = False`
  (`UNAVAILABLE(authid-empty)`). CRS lookup failure → `UNAVAILABLE(reason)`.
- Geometry type is an opaque string at discovery time (QGIS 4 enum repr
  drift risk per M1 §22 — verified on QGIS 4.2.0: `str()` of
  `Qgis.GeometryType` yields the int, with Point=0, Line=1, Polygon=2,
  Unknown=3, Null=4; the frozen mapping table lives in
  `contracts.canonicalize_geometry`); canonicalization to a closed enum happens in
  validation (§7), not discovery.
- Extent/fields that require expensive provider queries are
  `UNAVAILABLE(deferred)` — discovery must never trigger full table
  scans, per-feature iteration, or *explicit* remote fetches. A
  requirement that needs a deferred field forces re-query at validation
  time, explicitly (§7 records the re-query).

### 2.3 Discovery is read-only and bounded

Discovery calls QGIS getters only (`mapLayers`, `crs`, `extent`,
`fields`, `featureCount`, `isValid`, `providerType`), on the main thread
(§1.2). It MUST NOT: add or remove layers, change CRS, start edits, or
open files beyond what QGIS already opened. It MUST NOT perform explicit
network fetches or reachability probing — but for `database` /
`remote-service` layers (WFS/WMS/remote OGR) getters such as `extent()`,
`fields()`, `featureCount()` can trigger *implicit* provider I/O
(capabilities fetch, `COUNT(*)`, `DescribeFeatureType`); discovery
tolerates this with timeouts and records `UNKNOWN`/`UNAVAILABLE` on
failure rather than failing the snapshot. Snapshot of >N layers (default
cap 500; numeric caps deferred to implementation config per §16, value
illustrative) truncates deterministically: keep the first N in `layer_id`
order, set `truncated: true` + `total_count`. Truncation propagates: a
verdict on a truncated snapshot carries `snapshot_id` + `taken_at` +
`truncated: true`, and §3.3 emits `truncated-inventory` instead of
`no-layer` (a truncated inventory can never prove absence).

## 3. AVAILABLE / DERIVABLE / MISSING classification

Authority: a deterministic predicate over (`DataRequirement`,
`LayerInventory`). The LLM (M5+) may propose requirements; it MUST NOT
classify — classification output is computed, and any LLM-provided label
is ignored (same pattern as M2/M3: model proposes, engine disposes).

### 3.1 AVAILABLE

All of: (a) ≥1 inventory layer matches geometry type (after §7
canonicalization — the predicate applies the §7 mapping table QGIS-free
to the opaque discovery strings for pre-checks; the normative mapping is
executed and recorded at validation, §7 item 5), required fields ⊆ layer
fields, CRS equal to the
requirement CRS or requirement `crs` omitted (usable as-is — any needed
reprojection makes it DERIVABLE, see §3.2, never silently AVAILABLE);
(b) layer `valid`, `reachable` ≠ KNOWN-UNREACHABLE; (c) no external fetch
needed; (d) coverage pre-check passes (see authority split below).
Evidence attached: `layer_id` + per-check pass list in fixed check order
(geometry → fields → CRS → reachability → coverage → validity).

Coverage authority split (AGENTS.md:1 — QGIS owns GIS math): the
QGIS-free predicate performs only cheap pre-checks in native CRS
(authid equality fast-pass; bbox fast-reject when both boxes share one
CRS) labeled `ESTIMATE`. The normative coverage verdict —
`area(intersection ∩ requirement) / area(requirement)` computed in the
requirement `crs_authid` via QGIS/GDAL authority (equal-area/geodesic
rule per implementation; naive degrees²-vs-m² comparison is a unit
error and is forbidden) — is executed at validation (§7 item 8,
Extent/coverage) and recorded
there. Inventory-level AVAILABLE on coverage is therefore provisional:
layer bounding boxes are necessary, not sufficient (holes, sparse OSM,
raster nodata, filtered interiors all pass bbox tests with no data
inside — documented limitation). `UNKNOWN`/`UNAVAILABLE` extent with a
non-null requirement extent is never AVAILABLE (MISSING `coverage-gap`
or `unknown-deferred`, never a pass).

### 3.2 DERIVABLE

AVAILABLE is false, AND there exists an explicit, bounded transformation
chain composed solely of §8 ops executed by QGIS/Processing over
AVAILABLE inputs, with no external data. Ops split by information
behavior (§8): information-preserving (`reproject-vector`, `clip`,
attribute `filter`) vs information-transforming (`join`,
`raster-to-vector`, `vector-to-raster`, `reproject-raster` — require
method params + warnings +
mandatory `DERIVED` provenance, §10). Notably: any required vector
reprojection is a DERIVABLE `reproject-vector` step (corrects the initial
draft, which let reprojectable data pass as AVAILABLE and would have
hidden transform error while contradicting §10's DERIVED rule). The chain
is enumerated
in the classification output (op + params + input refs) — a bare
"derivable" verdict without the chain is invalid. Chain selection is
deterministic: shortest chain first, ties broken by §8 op order, then
input `layer_id` order. Cost bounds (max steps, max output size) are part
of the chain record (numeric caps deferred to implementation per §16;
until frozen, `transform-exceeds-bounds` evaluates against chain-length
only). Join-derived verdicts are provisional (join-key validation lives
in §7; validation confirms or downgrades).

### 3.3 MISSING

Otherwise. The output MUST distinguish sub-reasons (machine-readable,
classification layer):
`no-layer`, `schema-gap` (missing fields listed), `crs-gap`,
`coverage-gap`, `unknown-deferred` (extent/fields/CRS unknown — must not
be reported as a gap), `invalid-candidate` (layers exist but `!valid` or
`EMPTY`), `truncated-inventory` (snapshot truncated — absence unprovable),
`license-unavailable` (acquisition scope: provider cannot supply license
terms — classification proceeds on metadata, acquisition is blocked),
`provider-offline` (a provider could supply it but none is
configured/reachable — distinct from "data does not exist"),
`transform-exceeds-bounds`. Retryability: `provider-offline` is
classification-retryable; acquisition-level retryables (`TIMEOUT`,
`RATE_LIMITED`, `QUOTA_EXCEEDED` from the §6 taxonomy) retry at download,
not classification — the two retry scopes are distinct. The
classification-sub-reason ↔ adapter-error mapping is frozen in §6
(e.g. `DATASET_NOT_FOUND` → `no-layer` at acquisition scope).

### 3.4 Determinism

Same (`requirement`, `inventory`) → same verdict + same evidence order.
Evidence preserves inventory order verbatim (inventory is `layer_id`
ordered per §1.3; no sorting/dedup by the classifier). `LayerInventory`
carries `snapshot_id` + `taken_at` + `truncated` into every verdict. No
timestamps in the verdict itself. Any LLM-supplied classification label
is ignored — conformance hook: pass a label, assert it has no effect on
the verdict.

## 4. Data requirement contract

Frozen shape (field names normative for the future M4 implementation).
Schemas reuse the minimal registry validator **as it exists**
(`registry.py`: single-string `type`, no nullable unions, no `enum`, no
ranges, no `anyOf` — the M3 lesson): optionality uses the absence
pattern (absent field = unconstrained; cf. M3-T04 §2.2
`target_criteria`), and closed-value/range rules use small custom checks
with dedicated tests. `null | X` unions are forbidden in requirement
schemas.

```text
DataRequirement v1.0 (input schema; additionalProperties: false):
  name: str                       # human label, escaped on display
  geometry: str                   # closed: Any|Point|LineString|Polygon|Raster|Table (custom check)
  required_fields: list[str]      # empty = no attribute constraint
  field_types: map[str,str]       # optional; values from closed QVariant subset (custom check)
  crs: { authid: str }            # optional; absent = any CRS (reprojection allowed → DERIVABLE)
  extent: { xmin, ymin, xmax, ymax: number, crs_authid: str }  # optional; absent = no coverage constraint
  coverage_threshold: number      # optional, fraction in (0,1], default 1.0 (=100%); ignored if extent absent (custom range check)
  temporal: { has_time: bool }    # optional; absent = no temporal constraint
  acceptable_sources: list[str]   # optional, default [local-project, local-file]; values local-project|local-file|provider:<id> (custom check vs registered provider_ids)
  transformations_allowed: list[str]  # optional, default all seven; closed: reproject-vector|reproject-raster|clip|filter|join|raster-to-vector|vector-to-raster (custom check); empty = no transformation permitted (must be AVAILABLE as-is)
```

Geometry mapping (frozen): `Any` matches any canonical geometry
including `Unknown`; typed values require equality with the §7 canonical
enum `{Point, LineString, Polygon, Raster, Table, Unknown}` after
canonicalization (Multi*/Z/M variants fold into their family at §7;
`Unknown` satisfies no typed requirement). `clip` = spatial subset,
`filter` = attribute subset, `join` = attribute-only join (spatial join
excluded in M4, §8). `provider:<id>` is a runtime-checked string pattern,
not a schema type.

Rules: unknown JSON fields rejected; empty `acceptable_sources` invalid;
`field_types` values restricted to the closed subset
`{String, Int, Double, Date, DateTime, Bool, StringList}` (unlisted →
requirement INVALID — fail-closed, explicit); provider type names are
normalized to the subset first via a frozen case-insensitive alias table
(`integer→Int`, `string→String`, `double/float/real→Double`,
`date→Date`, `datetime/timestamp→DateTime`, `bool/boolean→Bool` — full
table in `contracts.normalize_field_type`, verified against real QGIS 4.2
`typeName()` output which yields lowercase names); coercion allowlist frozen:
exact-type match + `Int→Double` widening only, everything else (notably
string→number on join keys) fails. `extent` validated
(`xmin<xmax`, `ymin<ymax`; CRS-range/antimeridian rules at
implementation).
`verification` (`UNVERIFIED|VERIFIED|PARTIAL`) is output-only with
two-schema enforcement: the input schema omits the field — present on
input → rejected (explicit beats silent-ignore); the stored record adds
it, set only by validation (§7). Name-collision note: requirement
`verification=PARTIAL` (partially verified requirement) and validation
`validity: PARTIAL(sampled N/M)` (sampled geometry-validity statement)
are distinct fields in distinct records sharing one word; both defined
here, neither aliases the other.

## 5. Controlled external providers

### 5.1 Categories (M4 scope)

1. **STAC catalogs** (allowlisted endpoints, e.g. Earth Search / Planetary
   Computer pattern per M1 §21) — raster + metadata.
2. **OSM via bounded Overpass + Nominatim** (02Agent/QuickOSM pattern per
   M1 §12: fixed hosts, area caps, tiled merge, cache).
3. **User-provided local files** (not external, but untrusted until
   validated — same validation path §7).
4. Deferred: generic public geo-APIs beyond the allowlist, satellite tasking
   APIs, credential-bearing commercial endpoints (no credential-vault design
   in M4; providers requiring secrets are M4-later with a scoped vault task).

### 5.2 The forbidden path, restated as mechanism

`LLM → arbitrary URL → download` is prevented structurally, not by policy
text: (a) adapters accept dataset IDs / structured queries only, never raw
URLs (URL fields in schemas are rejected); (b) each adapter owns a
frozen allowlist of hosts; (c) network egress happens only inside the
governed tool handler after permission + confirmation + intent audit
(ADR-0010 lifecycle); (d) the future planner's tool schemas expose no URL
parameter. There is no code path from planner text to socket.

### 5.3 Quotas and limits (frozen policy shape)

Every provider adapter declares: max area per request, max bytes per
download, max assets per dataset, timeout, retry-with-backoff budget, and
cache TTL. Requests exceeding caps are rejected before execution (not
truncated silently). Values are provider-specific config, but the *fields*
are mandatory in the adapter interface (frozen in §6 below).

## 6. Provider adapter interface (frozen)

Extends `PROVIDER_CONTRACT.md`'s conceptual sketch into a frozen surface,
with one deprecation: `connect(resource)` is dropped — an opaque resource
handle is a URL passthrough risk (it would reintroduce arbitrary-address
connection through the back door). All addressing flows through
`(provider_id, dataset_id, asset_id)` identity + the adapter's frozen host
allowlist. Method names normative; signatures JSON-shaped
(registry-validator compatible); all methods return
`(ok, payload | error_code)` with a closed error taxonomy
(`PROVIDER_OFFLINE`, `DATASET_NOT_FOUND`, `AUTH_REQUIRED`, `QUOTA_EXCEEDED`,
`RATE_LIMITED`, `CHECKSUM_MISMATCH`, `LICENSE_UNAVAILABLE`, `TIMEOUT`,
`INVALID_QUERY`):

- `provider_id() -> str` (stable, e.g. `stac.earth-search`,
  `osm.overpass`); `provider_version() -> str`.
- `search(query, page_token?) -> {results: list[DatasetSummary],
  next_page_token?, total?}` — structured query only (bbox, datetime,
  collection, limit, key/value tags with allowlisted keys + escaped
  values); paginated (page token + total; input `limit` capped by
  `limits().max_results`); never free text passed to a URL except the
  single Nominatim `place` string, which is URL-encoded + length/charset
  capped + never interpolated into QL/HTML; never raw Overpass QL from
  untrusted input (QL, if ever used, is constructed from validated enums
  by the adapter).
- `get_metadata(dataset_id) -> DatasetMetadata` (title, date/version,
  license SPDX + attribution, asset list with sizes/checksums, CRS, extent).
- `get_assets(dataset_id) -> list[Asset]` (`asset_id`, bytes, sha256 if
  published, media type).
- `download(dataset_id, asset_id, sandbox_dir) -> LocalFile` — writes ONLY
  inside the provided sandbox dir (safe-join enforced, §9); streams with
  byte cap; verifies checksum when published; returns
  `LocalFile{sandbox_relpath, bytes, sha256_actual}` (relative path —
  reconciled with §10 `subject.ref`).
- `attribution(dataset_id) -> str`; `license(dataset_id) -> {spdx, text}`.
- `limits() -> {max_area_km2, max_bytes, max_assets, max_results,
  timeout_s, retries, cache_ttl_s, max_archive_members,
  max_unpacked_bytes, max_decompression_ratio, nominatim_req_per_s}`
  (mandatory fields; security caps live here alongside quota caps).
- Error→MISSING mapping (acquisition scope): `DATASET_NOT_FOUND` →
  `no-layer`; `LICENSE_UNAVAILABLE` → `license-unavailable`;
  `QUOTA_EXCEEDED`/`RATE_LIMITED`/`TIMEOUT` → retryable acquisition
  errors (not classification states); `AUTH_REQUIRED` → fail-closed error
  (M4 has no credential vault — §5.1 item 4 — so any auth challenge fails
  rather than prompting for secrets); `PROVIDER_OFFLINE` →
  `provider-offline`.

Egress-URL rule (ai-security review): **every** egress URL — including
provider-supplied STAC asset `href`s and every redirect target — is
validated against the adapter host allowlist *before connect*, with
resolved-IP (not hostname-string-only) RFC-1918/link-local blocking to
resist DNS-rebinding href/redirect attacks. Signed URLs (SAS `?sig=`,
tokens): blob/signing hosts must be enumerated in the allowlist or the
signed flow is rejected until the vault task; stored `source_url` is
query-stripped (host+path only) or omitted if signed (§10).

Adapters MUST NOT: open GUI, read/write outside sandbox, store
credentials (M4 has no vault), log URLs with query secrets,
perform GIS math (they fetch bytes; QGIS interprets them).

## 7. Validation model (frozen)

Authority: QGIS/PyQGIS + GDAL (AGENTS.md:1). The Data Engine orchestrates
checks and records evidence; it MUST NOT reimplement CRS math, geometry
predicates, or format parsing in pure Python.

Ordered checks (first failure wins, evidence recorded per check).
Probe layers are constructed but never auto-added to the project, on the
main thread (§1.2):

1. **Allowlist/type gate (single, merged)**: suffix + magic-byte
   allowlist (`.gpkg .shp(+sidecars) .geojson .json .tif .tiff .vrt .csv
   .zip`; executables/script suffixes rejected outright). Anything
   outside the allowlist → `UNSUPPORTED_FORMAT` error here — never
   best-effort parsing downstream.
2. **Integrity**: sha256 vs published checksum when available; size sanity
   (nonzero, ≤ adapter `max_bytes`); archive listing before extraction
   (see §9).
3. **Parseability**: open via `QgsVectorLayer`/`QgsRasterLayer` (or
   GDAL open for pre-screen); invalid → error with provider + asset id.
4. **Emptiness short-circuit**: zero features → `EMPTY` verdict
   immediately (skips geometry sampling, schema, extent — all recorded as
   `skipped-empty`). EMPTY satisfies no data-presence requirement, period:
   classification maps it to MISSING (`invalid-candidate` for layer refs,
   never AVAILABLE/DERIVABLE). EMPTY is reportable, not an exception.
5. **Schema** (cheap header check before scans): required fields ⊆ layer
   fields with §4 coercion allowlist (exact-type + Int→Double; no silent
   string→number for join keys). Join-key validation (for chains
   containing `join`): the join key must exist in both inputs with
   coercion-compatible types, contain no nulls, and contain no duplicates
   on the join side required 1:1 (left 1:1 enforced; 1:N, null keys,
   duplicate keys → INVALID with the failing condition named). This is
   the check §3.2's provisional join verdict defers to.
6. **CRS**: `crs.isValid()`; missing CRS → `crs_known=false`, usable only
   for aspatial/table use (requirement `crs` omitted AND no spatial op in
   the chain); missing CRS + any spatial check or non-null requirement
   extent → `crs-gap` MISSING (assigning a CRS by guess is new
   information, never derivation). Mismatch with both sides defined →
   reprojectable check else fail.
7. **Geometry validity**: per-feature validity via
   `QgsGeometry.isGeosValid()` / `validateGeometry()` over `getFeatures()`
   — NOT layer `isValid()` (which means "layer opened", a §3.1/validation
   input, not feature validity). Deterministic sampling: full scan at or
   below the row cap; above it, feature-id-ordered head sample, recorded
   as `validity: PARTIAL(sampled N/M)` with the frozen selection rule
   (order + method, no RNG). `PARTIAL` propagates as a warning that
   blocks validity-sensitive downstream ops (overlay, polygonize, join
   execution) until full validation/repair — classification treats
   `PARTIAL` as provisional, never final AVAILABLE for sensitive chains.
8. **Extent/coverage**: normative QGIS/GDAL coverage computation per §3.1
   authority split (formula + unit rule), at `coverage_threshold`; also
   re-queries any `UNAVAILABLE(deferred)` extent/fields from §2.2 here,
   explicitly recorded.

Validation output: `ValidationReport{verdict: VALID | EMPTY | INVALID,
checks: [...], crs_authid, geometry_canonical, field_list, extent,
feature_count_or_UNKNOWN, warnings[]}`. Canonical geometry enum lives
here (not discovery): `{Point, LineString, Polygon, Raster, Table,
Unknown}` mapped once from the QGIS 4 repr.

## 8. Transformation boundary (frozen)

Transformations are **declared, not computed**, by the Data Engine:

```text
TransformationStep: { op, op_version, params, input_refs[], output_ref, executor: qgis-processing }
ops (closed set, M4): reproject-vector | reproject-raster | clip | filter | join | raster-to-vector | vector-to-raster
```

Definitions (frozen): `clip` = spatial subset; `filter` = attribute
subset with a structured predicate (`{field, op, value}` from allowlisted
operators — never a raw QGIS expression string from untrusted input);
`join` = attribute-only join (spatial join excluded in M4). Information
behavior split (corrects the initial draft's blanket "no new
information" cover):

- Information-preserving (modulo numeric precision): `reproject-vector`,
  `clip`, attribute `filter`.
- Information-transforming (require method params + warnings + mandatory
  `DERIVED` provenance, §10): `join` (attribute enrichment creates new
  columns; cardinality policy frozen: 1:1 required, 1:N rejected, null
  keys rejected, duplicate keys rejected), `raster-to-vector` /
  `vector-to-raster` (interpolation, thresholding, nodata decisions),
  `reproject-raster` (resampling + datum-shift uncertainty).

Rules: op + params fully specified before execution (no interactive
tuning, no smuggled defaults — the explicit-method rule covers raster
`reproject-raster`/`clip` snap/nodata/edge as well as conversions); executor is
always a QGIS/Processing algorithm (id + version pinned in `op_version`)
invoked through a governed tool (confirmation per risk); each step
appends to the provenance chain (§10); chain length and output-size caps
enforced pre-execution; `output_ref` lifecycle frozen: memory-layer
(Uris) or sandbox file, recorded in provenance, never an absolute
outside-sandbox path. **Merge/mosaic decision (frozen): no `merge` op in
v1** — tiled local partials that jointly cover a requirement are MISSING
(`coverage-gap`) by design, because seam/nodata/overlap-resolution
policies are interpretive decisions outside M4 scope; documented here so
the gap is explicit, not silent. No transformation code in M4-T01; per-op
param schemas and executor bindings are an M4-T02 task.

## 9. Security model

Trust boundaries: (T1) planner/LLM text — untrusted, never executed,
never a URL; (T2) layer metadata/names — untrusted display strings
(prompt-injection threat per SECURITY_MODEL.md: escape, never interpolate
into queries/HTML); (T3) provider bytes/archives — untrusted until §7
passes; (T4) sandbox dir — the only writable location for acquired data;
(T5) project layers — trusted for reading, never mutated by discovery.

Mitigations (each mapped to SECURITY_MODEL.md future-threat list):

- Arbitrary URL/SSRF: host allowlists per adapter; no URL-typed schema
  fields; every egress URL (incl. STAC `href`s) + every redirect target
  validated pre-connect with resolved-IP (not hostname-string-only)
  RFC-1918/link-local blocking. DNS-rebinding beyond that is an accepted
  risk for M4 (no secrets/cloud-metadata credentials to steal,
  allowlisted hosts not attacker-controlled) + implementation TODO for
  check-after-resolve enforcement.
- Path traversal (POSIX + Windows): safe-join (resolve + prefix-check)
  for every write; archive members rejected on absolute paths (`/`,
  `C:\`, `\\UNC\`), `..`, backslash tricks, symlinks, hardlinks, NTFS
  ADS streams, device files; single sandbox root per acquisition.
- Malicious archives: pre-listing, member count + total-size caps,
  extension re-check per member, no executable extraction, no execution
  ever (SECURITY_MODEL.md: "No downloaded binary is executed").
- Oversized downloads/decompression bombs: byte caps on stream +
  decompression-ratio guard (abort past ratio; illustrative value 100× —
  numeric caps deferred to implementation config per §16).
- Untrusted parsing: parse only via QGIS/GDAL in-process with invalid
  handling to error paths (no `eval`/`exec`/`subprocess`/pickle/yaml-load
  anywhere in `lunar_gis/data` — static ban, enforced by the existing
  bandit quality gate). `/vsicurl/` range reads, if used, go through the
  same allowlist/cap/audit wrapper — GDAL must not bypass adapter
  accounting.
- Credentials: M4 stores none; redaction of connection strings at
  discovery (§2.1); audit records carry dataset IDs, never URLs with
  secrets, never local usernames/home paths beyond the minimum needed
  (AGENTS.md:10).
- Temp files: `tempfile` in sandbox root, created restrictive
  (`0600` POSIX / equivalent ACL on Windows), tracked in the
  acquisition record, cleaned on success/failure paths (lease: orphan
  sweep on next acquisition records the sweep in audit).
- Prompt-injection scope: T2 escaping + §4 display-escaping + §6
  no-free-text/no-raw-QL cover query-injection and stored-XSS/display
  threats, and M4 has no AI integration (§0), so the residual
  LLM-instruction-following risk from crafted names/metadata is contained
  by propose-but-never-classify (§3) + summaries-only consumption (§13)
  + search/download split with confirmation (§12). **M5-must:** planner
  design must add trust-labeling of untrusted summary segments (never
  concatenate into system prompts); §9 alone is not an LLM-injection fix
  and must not be cited as one.
- Threat-mapping scope: denial-of-service-through-processing is covered
  via chain/output caps (§8) + search/download caps (§6); local-upload
  and AI-context-minimization threats belong to M5 planner scope and are
  not claimed here.

## 10. Provenance model (frozen minimum record)

Minimum provenance record (frozen field names; JSON-compatible):

```text
DataProvenance v1.0:
  subject: { kind: layer-ref | file, ref: layer_id | sandbox_relpath }
  origin: { kind: project | local-file | provider,
            provider_id?, provider_version?, dataset_id?, asset_id? }
  requirement_ref?: str     # DataRequirement name/id this acquisition satisfies
  validation: { verdict: VALID|EMPTY|INVALID, report_ref: str }?
  source_url?: str          # host+path only, query/fragment stripped; omitted if signed or non-allowlisted (never arbitrary, never SAS)
  license: { spdx: str, attribution: str }
  retrieved_at: ISO-8601 UTC  # acquisition time, not analytical content
  dataset_version?: str     # provider date/version; absent if unpublished
  sha256?: str              # bytes checksum; per-step input hashes in transforms[]; absent only for live layer-refs (see snapshot pin)
  snapshot_pin?: { snapshot_id, taken_at, feature_count, extent, field_list }
  crs_authid?: str
  transforms: list[TransformationStep]  # empty = original; each step carries input sha256s + executor algorithm id+version
  status: ORIGINAL | DERIVED
  tool_invocations: list[{tool_name, tool_version, policy_decision_ref}]
```

Rules: externally sourced or materially transformed ⇒ record mandatory;
`DERIVED` requires non-empty `transforms`; license `NONE-declared` is
explicit (never null-meaning-clear); attribution text propagated to any
future report/cartography output; retrieval timestamps are audit metadata
(same envelope philosophy as M3-T04 §7.4). Live layer-refs (no stable
bytes) pin the §1.3 snapshot instead of a hash: `snapshot_id` +
`taken_at` + `feature_count` + `extent` + `field_list` make later drift
detectable. File-layer `source` paths minimize home directories
(basename/relpath + `utils` redaction, AGENTS.md:10).

## 11. Offline behavior

Always available offline: project discovery snapshot, requirement
authoring, classification against the snapshot, deterministic engines
(AHP/sensitivity), validation of local files, transformation *planning*
(chain construction). Qualification: "execution needs QGIS, which is
local" holds only for native local algorithms — transforms/validation
over `remote-service` layers or network-backed Processing still need
network and return `provider-offline` MISSING without probing
reachability. Providers are optional: classification emits
`provider-offline` MISSING sub-reason (retryable) rather than failing;
no provider import at `lunar_gis.data` import time (lazy adapter loading
keeps `import lunar_gis.data` QGIS-optional for pure contracts,
stdlib-only where possible — M3-T03-F1 lesson: M3-T03 follow-up 1, QGIS
Processing acceptance-findings resolution, commit `41b03f2`).

## 12. Governed tool boundary

Future tools (names/versions normative; schemas/implementation deferred to
M4-T02+). All follow the 12-step ControlledExecutor lifecycle with intent
+ terminal audit records; confirmation artifacts bind tool+input+context
fingerprints (execution.py precedent).

| Tool | Risk | Confirm | Input (shape) | Output (shape) | Deterministic/offline |
|---|---|---|---|---|---|
| `data.describe_project` v1 | READ | no | `{include_fields: bool}` | `LayerInventory` | yes/yes |
| `data.check_requirement` v1 | READ | no | `DataRequirement` + inventory ref | verdict + evidence (`AVAILABLE/DERIVABLE/MISSING`) | yes/yes |
| `data.search_catalog` v1 | MEDIUM | no (search is read-only; capped by `limits()` incl. `max_results`; intent-audit still recorded; Nominatim 1 req/s + cache honored) | provider_id + structured query | `{results, next_page_token?, total?}` | bounded/no |
| `data.download_dataset` v1 | HIGH | **yes** (meaningful download, AGENTS.md:9) | provider_id + dataset_id + asset_id | `LocalFile` + `DataProvenance` | no/no |
| `data.validate_dataset` v1 | LOW | no | subject ref | `ValidationReport` | yes/yes |
| `data.register_local_file` v1 | LOW | no | `sandbox_relpath` (safe-joined, never absolute — else arbitrary-file-read probe) + declared schema | `DataProvenance` (origin local-file) | yes/yes |
| `data.run_transformation` v1 | HIGH | **yes** (destructive/expensive, AGENTS.md:9; destructive ops per SECURITY_MODEL.md) | `TransformationStep[]` | derived ref + appended provenance | via QGIS/local |

`data.download_dataset` and `data.run_transformation` are the only
confirmation-gated tools (artifact bound to exact dataset/asset/steps).
Search-then-download are separate invocations (no auto-download of search
hits — the `02Agent` validated-proposal pattern: bounded Overpass +
proposal + explicit user approval before the Processing run, per
M1 §12). The engine creates one sandbox per acquisition and passes
`sandbox_dir` to the adapter — tools never accept caller-supplied
absolute paths.

## 13. QGIS / Processing / AI responsibility split

| Concern | Data Engine (`lunar_gis/data`) | QGIS/PyQGIS/GDAL | Processing adapter | Future AI planner (M5+) |
|---|---|---|---|---|
| Layer listing/metadata snapshot | defines schema, orchestrates | answers getters | — | consumes summaries only |
| AVAILABLE/DERIVABLE/MISSING | computes predicate + evidence | — | — | proposes requirements; never classifies |
| Fetch bytes | adapter allowlist + sandbox + audit | — (transport via Python stdlib/`QgsFileDownloader` at implementation; decision deferred) | — | never touches network |
| Validate/interpret bytes | orchestrates, records | executes all GIS checks | transformation algorithms | — |
| Transform math | declares steps only | executes | hosts algorithms as governed tools | — |
| Provenance | defines shape + emits records; `provenance` stores/audits (per §1.2) | — | propagates invocation refs | cites, never invents |

Transport note (deferred decision): stdlib `urllib` vs
`QgsFileDownloader` for adapter downloads — decided at implementation
against frozen criteria: `urllib` is synchronous (blocks calling thread),
ignores QGIS proxy/auth settings, follows redirects by default (must
disable + re-check allowlist, reject RFC-1918/link-local), needs manual
timeout/SSL/cancel; `QgsFileDownloader` is async Qt-network honoring QGIS
proxy/auth with native progress/cancel, but has main-thread `QObject`
affinity, needs an event loop, still-manual redirect/sandbox handling,
and Qt6 signal/enum verification. Either is viable only inside the
§5.2/§9 wrapper. No LLM math, no LLM file/URL handling, in any row
(AGENTS.md:1,2,5).

## 14. OSS / provider audit

M1 §§12–16,21,23 already audited agent/plugin candidates; this section
adds Data-Engine depth and re-verdicts provider-relevant projects only.
Licenses checked against GPL-2.0-or-later distribution; no dependency
added in M4-T01; no code copied (AGENTS.md:12).

| Candidate | Repo/site | License (verified) | Capability | Verdict |
|---|---|---|---|---|
| PySTAC (`stac-utils/pystac` v1.15.1) | github.com/stac-utils/pystac | Apache-2.0 (verified 2026-09-18, pyproject `license={text="Apache-2.0"}`) | STAC Item/Collection/Catalog read, search-client base | **ADAPT (optional dep)** — search/get_metadata/get_assets/download/attribution/license behind adapter interface; Apache-2.0 → GPL-2.0-or-later compatible as optional dependency (M1 §21 consistent) |
| pystac-client | github.com/stac-utils/pystac-client | Apache-2.0 | STAC API search + pagination | **ADAPT (optional dep, with PySTAC)** — pagination/bbox/datetime query shape informs `search(query)`; same license basis |
| Planetary Computer SDK (`microsoft/planetary-computer`) | github.com/microsoft/planetary-computer | MIT | signed asset URLs, SAS handling | **ADAPT concepts** — signed-URL + subscription pattern; signing keys are credentials ⇒ M4 stores none (§9), so deliberately downgraded from M1 §21's optional-dep to pattern reference until the vault task |
| QuickOSM (`3liz/QuickOSM`) | github.com/3liz/QuickOSM | GPL-2.0 | bounded Overpass key/value fetch, 400k+ installs | **ADAPT pattern; INTEGRATE optional via Processing** — GPL-2.0 → GPL-2.0-or-later compatible; optional Processing dependency, never core pip dep (M1 §21 consistent) |
| 02Agent-OSM-Downloader | github.com/YusufEminoglu/02Agent-OSM-Downloader | Other/Source-Available (not GPL/MIT) | 4 fixed hosts, area caps, tiled merge, validated proposal + approval | **ADAPT pattern only, DO NOT copy, DO NOT pip-dep** (license incompatible with GPL reuse; M1 §§16/23 verdicts); M1's optional-Processing-integration carve-out is unchanged (at-arms-length plugin use, never pip distribution) |
| Nominatim (usage policy) | nominatim.org | GPL-2.0 (software); data ODbL; strict usage policy (1 req/s, referer, caching) | place → bbox geocoding | **ADAPT with policy compliance** — rate limit + attribution + caching mandatory in adapter limits (§6 `limits()`); usage-policy violation is a misuse risk, not a license block |
| OSMnx (`gboeing/osmnx`) | github.com/gboeing/osmnx | MIT (verified 2026-09-18) | street-network/graph modeling, heavy stack (pandas/geopandas/shapely/pyproj/networkx) | **REJECT (runtime), REFERENCE-ONLY** — new M4 depth (no M1 verdict to contradict): MIT compatible but dependency weight + in-memory graph scope exceed M4 bounded-fetch needs; Overpass needs covered by QuickOSM/02Agent patterns |
| GDAL `/vsicurl/` + `QgsFileDownloader` | bundled with QGIS/GDAL | MIT/X (GDAL) / GPL (QGIS runtime env) | range reads of remote COGs without full download | **ADAPT technique, no new dep** — already in runtime; informs §13 transport + signed-URL handling |
| qgis-stac-plugin pattern (GeoAgent observation, M1 §14) | `qgis-stac` ecosystem | GPL-2.0 family | background-task COG add with status-bar feedback | **ADAPT pattern** — UX pattern for long fetches; no code dependency |
| sentinelsat | github.com/sentinelsat/sentinelsat | GPL-3.0 | Copernicus SciHub search/download | **REJECT (runtime)** — GPL-3.0 requires GPL-3.0 distribution, incompatible with GPL-2.0-or-later (M1 §21 consistent); prefer STAC/Planetary Computer path |
| geopy | github.com/geopy/geopy | MIT | Nominatim client (rate-limited, cached) | **ADAPT optional** — candidate transport for Nominatim adapter behind interface; decision at implementation |
| fiona / rasterio / shapely / pyproj (direct) | various | BSD-3 (fiona/rasterio/shapely); MIT (pyproj) — all permissive | vector/raster I/O outside QGIS | **REJECT** — QGIS/GDAL already provide `QgsVectorLayer`/`QgsRasterLayer`; no parallel stack in a QGIS plugin (M1 §21 consistent) |
| Missing-license agent repos (qgis-ai-agent, AgenticGIS, geo-knowledge-ai, OSM-AI; missing-license status per M1 §13 license table) | various | not identified → treat as ARR | various data-fetch snippets | **REJECT copy/dep** — unchanged from M1 §23; license posture does not improve with reuse need |

Supply-chain note: ADAPT-optional rows (PySTAC, pystac-client, geopy)
become `[project.optional-dependencies] data` candidates at implementation
— never core `dependencies` (QGIS plugins should minimize pip surface;
offline rule favors lazy imports). Pattern-only rows add zero surface.

## 15. Frozen decisions (M4-T01)

1. Local-first order: snapshot → requirement → classify → local fulfill →
   controlled acquire (ADR-0003 operationalized).
2. Classification predicate authority + evidence + sub-reasons incl.
   retryable `provider-offline` (§3).
3. `DataRequirement v1.0` shape + output-only `verification` (§4).
4. Adapter interface method set (with `connect()` deprecation rationale),
   error taxonomy incl. `AUTH_REQUIRED`/`RATE_LIMITED`, mandatory limit
   fields incl. security caps, structured-query-only rule, egress-URL and
   signed-URL rules (§6).
5. Validation ordered checks (merged gate, emptiness short-circuit,
   schema-before-scans) + `VALID/EMPTY/INVALID` + QGIS authority +
   `isGeosValid` terminology + deterministic sampling + PARTIAL/EMPTY
   propagation (§7).
6. Transformation closed op set with preserving/transforming split +
   record-only engine role + merge-exclusion decision (§8).
7. Minimum provenance record + ORIGINAL/DERIVED rule + snapshot pin +
   query-strip (§10) + redaction (§2.1 discovery, §9 audit rules).
8. Trust boundaries T1–T5 + mitigations incl. static `eval/exec/subprocess/
   pickle` ban in `lunar_gis/data` (§9).
9. Offline guarantees + lazy adapter loading (§11).
10. Seven governed tools with names/versions/risk/confirmation (§12).
11. Dependency policy: zero new runtime deps; optionals only (§14 note).
12. M4-T01 creates only ADR-0012 (see §17): boundaries recorded there;
   further M4 splits may require new ADRs.

## 16. Deferred decisions

- Adapter transport (`urllib` vs `QgsFileDownloader`) — implementation,
  decided against §13 criteria.
- Numeric caps (area/bytes/ratios/timeouts) — implementation config
  (illustrative values in §§2/9 are non-normative).
- Credential vault for secret-bearing providers — scoped M4-later task.
- Geometry sampling row cap, QVariant subset extensions — implementation
  (coercion allowlist itself is frozen in §4).
- `canonical_report_bytes`-style canonical bytes for DataResult — M4-T02+.
  (M3-T04 term: the planned `canonical_report_bytes()` function that
  produces the hashable byte form of a report model.)
- `sensitivity_params_hash`-analog dataset-content binding beyond sha256 —
  only if sha256 proves insufficient. (M3-T04 term: the proposed separate
  hash binding sweep parameters alongside the matrix-only `input_hash`.)
- Generic public-API providers beyond allowlist; satellite tasking; mesh
  beyond identification; temporal modeling; join-key inference.
- Any M5 planner design (this doc defines what the planner may consume
  and what it may never do — nothing more).

## 17. Documentation / ADR changes

- New: `docs/research/M4-DATA-ENGINE-DESIGN.md` (this document).
- Update: `docs/research/README.md` index line.
- New: **ADR-0012** (`docs/adr/ADR-0012-data-engine-boundary.md`,
  status Proposed pending this panel) — why: existing ADRs are
  insufficient in three precise ways: (a) ADR-0003 names the
  AVAILABLE/DERIVABLE/MISSING states but defines no predicate, evidence,
  or authority; (b) `PROVIDER_CONTRACT.md` sketches method names but
  freezes no versions, error taxonomy, limit fields, or security binding;
  (c) ADR-0004 assigns `lunar_gis/data` one responsibility line and import
  rules but no detailed Data Engine responsibilities
  (snapshot/requirement/predicate/validation-orchestration/
  transform-records/provenance/sandbox policy) and no QGIS-free-testability
  rule. ADR-0012 records the §15 frozen contracts at decision level (one
  page, pointers here) and explicitly amends ADR-0004's `agent`/`reports`
  import rows.

## 18. M4-T02 implementation notes

M4-T02 implements the QGIS-free contracts and local discovery subset.
Deviations and v1-scope pins relative to the frozen design above (all
within frozen latitude; no ADR change):

- v1 classifier enumerates single-step chains only; multi-step
  composition is an M4-T03+ seam (symbolic `output_refs`).
- `clip`/`filter` are accepted schema values but never emitted by v1
  enumeration (satisfied clip preconditions already classify AVAILABLE;
  filter predicates are not representable in `DataRequirement v1.0`).
- Join cardinality ships as `1:1-proposed` (validation confirms per §7).
- Temporal evaluates as a trailing check after validity (check order
  geometry→fields→CRS→reachability→coverage→validity→temporal).
- QGIS 4.2.0 verified: `str(Qgis.GeometryType)` yields ints
  (Point=0, Line=1, Polygon=2, Unknown=3, Null=4); `QgsField.typeName()`
  yields lowercase names (normalized via frozen alias table).
- Provider prefix→storage table and `MAX_CHAIN_STEPS=3` are
  implementation config (non-normative) per §16.
- `MissingReason` v1 snapshot subset only (8 values); `provider-offline` /
  `license-unavailable` are acquisition-scope (design §6), owned by
  provider tasks, never emitted by `classify_requirement` v1.
- v1 fulfills the `local-project` snapshot path only; `local-file` /
  `provider:<id>` sources are accepted but unevaluated (M4-T03+ seam).
- `coverage_threshold<1.0` with partial overlap → `unknown-deferred`
  (no QGIS-free area ratios).
- Join key = first `sorted(common)` coercible pair (frozen `COERCIBLE`
  table), `cardinality` shipped as `1:1-proposed`.
- Reproject branches require ESTIMATE coverage too: CRS-mismatch +
  extent-mismatch combinations never emit single-step chains (coverage
  re-validated QGIS-side in M4-T03+).

## 19. References

1. AGENTS.md rules 1–12; ADR-0001…ADR-0012; MILESTONES.md (M4 Data Engine).
2. `docs/providers/PROVIDER_CONTRACT.md`; `docs/security/SECURITY_MODEL.md`.
3. `docs/research/M1-OSS-REUSE-AUDIT.md` §§12–16, 21–23.
4. `lunar_gis/agent/registry.py` (ToolSpec/ToolRisk/ToolVersion, minimal
   validator incl. no-nullable-types limitation), `governance.py`
   (PolicyDecision/ConfirmationDecision/AuditRecord),
   `execution.py` (12-step lifecycle, ConfirmationArtifact fingerprints).
5. `lunar_gis/project/context.py` (LayerSummary defensive pattern).
6. M2/M3 deterministic-engine precedent: frozen dataclasses, policy
   versions, input hashes, QGIS-free pure modules, M3-T04 report-model
   philosophy (no second source of truth, envelope timestamps).
