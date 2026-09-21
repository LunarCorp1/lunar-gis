# Milestones

Status legend: ✅ implemented + tested + reviewed + gated.

## M0 Foundation — ✅ current (superseded by M1+)
- Repository structure
- OpenCode governance
- Plugin metadata
- Minimal plugin shell
- Tests/CI skeleton
- ADR system

## M1 Project Context + Tool Registry — ✅
- QGIS project/layer inventory
- Layer metadata summaries
- Versioned tool contracts
- Validation
- Permission model
- Audit events

## M2 AHP — ✅
- Pairwise matrix
- Weights
- lambda max
- CI/CR
- Sensitivity analysis
- Processing algorithm + tool integration

## M3 AHP Sensitivity — ✅ (engine + tools + Processing; reporting design accepted)
- Weight perturbation, stability intervals, crossovers
- Tool + Processing integration

## M4 Data Engine — ✅
- Local file inspection (validation engine)
- Data contracts + classification (AVAILABLE/DERIVABLE/MISSING)
- Transformation engine (7 ops, Processing-backed)
- Provenance records + audit store
- Provider abstraction (STAC, OSM/Overpass, Nominatim) + SSRF-safe transport
- Fulfillment orchestration + governed data tools

## M5 OpenRouter AI — ✅
- Provider abstraction
- Structured outputs
- Tool planning
- Context assembly (privacy-controlled, trust-labeled)
- Safe execution (registry-validated tool calling)

## M6 GIS Analysis Tools — ✅
- Buffer, intersection, dissolve, zonal statistics, spatial join
- Governed tools + Processing algorithms

## M7 AutoCartography — ✅
- Deterministic styling (Okabe-Ito), layouts, legend/scalebar/north-arrow/provenance
- QA checklist, PDF/PNG export

## M8 Reports + Reproducibility — ✅
- Reproducible analytical content (timestamp-free identity)
- Accessible HTML reports, export

## M9 Product Integration — ✅
- 8-tab UI workspace, confirmations, offline mode
- End-to-end suitability workflow test
- Fresh-install verification

## M10 Advanced GIS (deferred)
- Kriging
- Hydrology
- Remote sensing
- Network analysis
- Advanced statistics
