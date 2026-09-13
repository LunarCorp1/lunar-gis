# OSM

Use when planning OpenStreetMap / Geofabrik integration — not for implementation in M0/M1.

## When to use

* Designing future `lunar_gis/data/` OSM provider adapter docs

## Must do

* Follow `AGENTS.md:5,6` and `docs/providers/PROVIDER_CONTRACT.md`.
* Read `docs/adr/ADR-0003-local-data-first.md` and `docs/security/SECURITY_MODEL.md` (download validation, no binary exec).

## Phase gate

> **MILESTONE GATE: M4 Data Engine — DO NOT implement in M0/M1.**

## References

* `AGENTS.md`, `docs/adr/ADR-0003-local-data-first.md`, `docs/providers/PROVIDER_CONTRACT.md`, `lunar_gis/data/__init__.py`

## Checklist

* [ ] No OSM download code in M0/M1
