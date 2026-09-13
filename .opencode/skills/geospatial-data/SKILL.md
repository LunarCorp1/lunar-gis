# Geospatial Data

Use when planning local file inspection or provider data acquisition — not for implementation in M0/M1.

## When to use

* Designing future `lunar_gis/data/` local inspection or `DataProvider` docs

## Must do

* Follow `AGENTS.md:5-8` (provider adapters, local-first, AVAILABLE/DERIVABLE/MISSING, provenance) and `docs/providers/PROVIDER_CONTRACT.md`.
* Read `docs/adr/ADR-0003-local-data-first.md` and `docs/security/SECURITY_MODEL.md` (archives untrusted, no binary exec, oversized datasets).
* Respect `docs/adr/ADR-0004-module-boundaries.md` (`data` → `provenance`/`project`, no `ai`/`cartography`).

## Phase gate

> **MILESTONE GATE: M4 Data Engine — DO NOT implement provider/local inspection beyond `project` context in M0/M1.**

## References

* `AGENTS.md`, `docs/adr/ADR-0003-local-data-first.md`, `docs/adr/ADR-0004-module-boundaries.md`, `docs/providers/PROVIDER_CONTRACT.md`, `docs/security/SECURITY_MODEL.md`

## Checklist

* [ ] No new data provider code in M0/M1
* [ ] Future design uses `AVAILABLE/DERIVABLE/MISSING` classification
