# STAC

Use when planning SpatioTemporal Asset Catalog integration — not for implementation in M0/M1.

## When to use

* Designing future `lunar_gis/data/` STAC provider adapter docs

## Must do

* Follow `AGENTS.md:5,6` (provider adapters, local data first) and `docs/providers/PROVIDER_CONTRACT.md` (`search`/`get_metadata`/`download`/`connect`).
* Read `docs/adr/ADR-0003-local-data-first.md` (AVAILABLE/DERIVABLE/MISSING) and `docs/security/SECURITY_MODEL.md` (archives untrusted, malicious URLs, path traversal).

## Phase gate

> **MILESTONE GATE: M4 Data Engine — DO NOT implement provider in M0/M1.** Skill is planning/reference only.

## References

* `AGENTS.md`, `docs/adr/ADR-0003-local-data-first.md`, `docs/providers/PROVIDER_CONTRACT.md`, `docs/security/SECURITY_MODEL.md`, `lunar_gis/data/__init__.py`

## Checklist

* [ ] No `stac` client code added in M0/M1
* [ ] Design respects `PROVIDER_CONTRACT.md` and local-first
