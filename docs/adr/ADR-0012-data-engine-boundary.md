# ADR-0012: Data Engine Boundary

- Status: Proposed
- Date: 2026-09-18
- Amends: ADR-0004 rows `agent`, `reports` (explicit May-import additions below)
- Review: pending architect, data-engineer, qgis-expert, gis-methodology-reviewer, ai-security-reviewer, dependency-license-auditor, test-engineer, documentation-reviewer; flips to Accepted only after M4-T01 findings close
- Deciders: architect, data-engineer, lunar-gis maintainers
- Related: AGENTS.md:1-12, ADR-0002, ADR-0003, ADR-0004, ADR-0010,
  docs/providers/PROVIDER_CONTRACT.md, docs/security/SECURITY_MODEL.md,
  docs/research/M4-DATA-ENGINE-DESIGN.md (full contract)

## Context

Existing architecture is insufficient for M4 in three precise ways:

1. ADR-0003 names the AVAILABLE / DERIVABLE / MISSING states but defines
   no classification predicate, no evidence, and no authority rule.
2. `docs/providers/PROVIDER_CONTRACT.md` sketches adapter method names but
   freezes no versions, error taxonomy, limit fields, or security binding.
3. ADR-0004 assigns `lunar_gis/data` one responsibility line (`Local file
   inspection, DataProvider adapters`) and import rules, but no detailed
   Data Engine responsibilities (snapshot/requirement/predicate/
   validation-orchestration/transform-records/provenance/sandbox policy)
   and no QGIS-free-testability rule.

M4-T01 freezes these contracts; this ADR records them at decision level.
Full field shapes, rules, and audits live in `M4-DATA-ENGINE-DESIGN.md`.

## Decision

1. `lunar_gis/data` owns discovery snapshots, the `DataRequirement v1.0`
   contract, the deterministic classification predicate (LLM never
   classifies), the versioned adapter interface with closed error taxonomy
   and mandatory limit fields, validation orchestration, transformation-step
   records, provenance-record emission (records stored/audited in
   `provenance`), and sandbox path policy.
2. `lunar_gis/data` MUST NOT import `agent`, `ai`, `cartography`,
   `reports`, `qgis.gui`/`qgis.PyQt`, or network clients directly; pure
   contracts stay QGIS-free importable/testable. GIS authority remains
   `qgis.core`/Processing/GDAL (AGENTS.md:1).
3. External acquisition flows only as `request → validated provider/tool →
   governed execution → provenance`. Adapters accept structured queries and
   dataset IDs, never raw URLs; each adapter owns a frozen host allowlist.
   `data.download_dataset` and `data.run_transformation` (both v1, HIGH)
   require explicit scoped confirmation; search never auto-downloads.
4. Local-first order is operational: snapshot → requirement → classify →
   local fulfill → controlled acquire (ADR-0003).
5. Zero new runtime dependencies; provider SDKs are optional-dependency
   candidates only.
6. Amends ADR-0004 (explicit, no silent drift): `agent` May import +=
   `data` (tool handlers only — no GIS math, no network, no QGIS GUI);
   `reports` May import += `data` (read-only `DataResult`/`DataProvenance`
   DTOs only — no fetch, validate, or transform calls). All other
   ADR-0004 rows unchanged.

## Alternatives considered

1. **Flat `data` monolith with no frozen contracts** — rejected: would
   leave classification authority, adapter surface, and provenance shape
   to implementer discretion, violating AGENTS.md:3 (validated versioned
   tools/schemas before execution).
2. **Recording the boundary only in the research doc (no ADR)** — rejected:
   the `agent`/`reports` import-row changes alter ADR-0004's normative
   table; silent table drift was already flagged by reviewers, so an
   explicit pointer-ADR is required.
3. **Immediate implementation alongside design** — rejected: M4-T01 is
   design-only by task scope; implementation belongs to M4-T02+.

## Consequences

- M4 implementation tasks must conform to the frozen §15 contracts in
  `M4-DATA-ENGINE-DESIGN.md`; deviations require an ADR amendment.
- `reports`/`cartography`/M5 planner consume `DataResult` + provenance;
  none of them fetch, validate, or transform data outside this boundary.
- The M1 provider verdicts (PySTAC/pystac-client optional ADAPT, QuickOSM
  pattern/optional, 02Agent pattern-only, sentinelsat REJECT, fiona/rasterio
  REJECT) stand and are extended by the M4-T01 audit table.
