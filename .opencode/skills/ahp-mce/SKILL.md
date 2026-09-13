# AHP/MCE

Use when planning deterministic multi-criteria analysis (pairwise matrices, weights, suitability) — not for implementation in M0/M1.

## When to use

* Designing future `lunar_gis/analysis/` AHP/MCE outside code changes (docs, review of methodology)

## Must do

* Follow `AGENTS.md:1,2` — QGIS/Processing owns GIS math; LLM never calculates final AHP/MCE weights.
* Read `docs/adr/ADR-0004-module-boundaries.md` (`analysis` → `qgis.core`, no `ai` for math) and `docs/architecture/MILESTONES.md` M2/M3.

## Phase gate

> **MILESTONE GATE: M2 (AHP) / M3 (MCE) — DO NOT implement in M0/M1.** This skill is planning/review only. Any code change requires milestone ADR and `gis-methodology-reviewer` approval.

## References

* `AGENTS.md`, `docs/adr/ADR-0004`, `docs/architecture/MILESTONES.md` (M2, M3), `lunar_gis/analysis/__init__.py`

## Checklist

* [ ] No `AHP`/`MCE` Python added in M0/M1
* [ ] If reviewing future math, note assumption and alternative normalization/sensitivity needs
