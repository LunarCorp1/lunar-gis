# QGIS Processing

Use when adding `QgsProcessingAlgorithm` or `QgsProcessingProvider` (M3/M9).

## When to use

* Creating future Processing provider (`lunar_gis/processing/` package, reserved via top-level `processing/.gitkeep` until M3) or wrapping deterministic raster/vector operations for `analysis` / `cartography`

## Must do

* Follow `AGENTS.md:1,6` — QGIS Processing owns execution; local data first.
* Read `docs/adr/ADR-0001-plugin-foundation.md` (“prefer stable QGIS APIs”) and `docs/adr/ADR-0004-module-boundaries.md` (`analysis` → `qgis.core/processing`, not `ai`).
* Keep algorithms deterministic, testable without LLM, with provenance via `lunar_gis/provenance/`.

## Phase gate

> **MILESTONE GATE: M3/M9 — DO NOT implement provider in M0/M1.** This skill is reference-only until `docs/architecture/MILESTONES.md` reaches M3.

## References

* `AGENTS.md`, `docs/adr/ADR-0001-plugin-foundation.md`, `docs/adr/ADR-0004-module-boundaries.md`, `docs/architecture/OVERVIEW.md`, `lunar_gis/analysis/__init__.py`

## Checklist

* [ ] `QgsProcessingAlgorithm` subclass has `initAlgorithm`, `processAlgorithm`, `createInstance`
* [ ] No arbitrary Python exec, no network in `processAlgorithm`
