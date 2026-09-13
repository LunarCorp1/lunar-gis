# Provenance

Use when recording dataset and workflow lineage.

## When to use

* Adding `lunar_gis/provenance/` lineage for transforms, downloads, or tool execution
* Wiring `lunar_gis/data/` provider or `lunar_gis/agent/` execution to provenance

## Must do

* Follow `AGENTS.md:8` — data transformations and external datasets must have provenance metadata; `docs/adr/ADR-0003-local-data-first.md` for AVAILABLE/DERIVABLE/MISSING.
* Read `docs/architecture/OVERVIEW.md` output+provenance and `docs/adr/ADR-0004-module-boundaries.md` (`provenance` → `utils` only).
* Record at minimum: source, provider, license, CRS, transform tool/params, QGIS/Lunar versions, workflow ID (see `docs/architecture/OVERVIEW.md` output+provenance).

## Phase gate

> **MILESTONE GATE: M6/M8 — provenance wiring expands at M1/M6, but do not add heavy lineage until then.** Skill is planning aid in M0.

## References

* `AGENTS.md`, `docs/adr/ADR-0003-local-data-first.md`, `docs/adr/ADR-0004-module-boundaries.md`, `docs/architecture/OVERVIEW.md`, `lunar_gis/provenance/__init__.py`

## Checklist

* [ ] No silent transforms — provenance entry created alongside output
