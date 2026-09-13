# Cartography

Use when planning automatic cartography, layout, or map QA — not for implementation in M0/M1.

## When to use

* Designing future `lunar_gis/cartography/` layout/style/QA or `docs/cartography/`

## Must do

* Follow `AGENTS.md:1,2` (QGIS owns GIS math; LLM never source of GIS) and `docs/adr/ADR-0004-module-boundaries.md` (`cartography` → `analysis`/`project`/`data`, no URL fetch).
* Read `docs/architecture/OVERVIEW.md` execution boundary and `docs/cartography/README.md` (reserved for M7).

## Phase gate

> **MILESTONE GATE: M7 AutoCartography — DO NOT implement in M0/M1.** Skill is planning/reference only.

## References

* `AGENTS.md`, `docs/adr/ADR-0004-module-boundaries.md`, `docs/architecture/MILESTONES.md` (M7), `docs/architecture/OVERVIEW.md`, `lunar_gis/cartography/__init__.py`

## Checklist

* [ ] No layout/style code added in M0/M1
