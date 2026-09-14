# Architecture Overview

## Current target

The first milestone intentionally implements only the QGIS plugin foundation, project/layer context, and safe tool-registry foundations.

## Planned bounded modules

```text
lunar_gis/
├── ai/            AI provider + planner contracts
├── agent/         Tool registry, validation, permissions, execution
├── analysis/      Deterministic GIS/mathematical analysis
├── cartography/   Layout/style/QA engine
├── data/          Local data + provider adapters
├── project/       QGIS project context
├── provenance/    Dataset and workflow lineage
├── reports/       Reproducible reports
├── ui/            PyQt/QGIS UI
└── utils/         Small shared utilities
```

## Execution boundary

```text
User intent
    ↓
AI planner (later)
    ↓
Versioned structured tool request
    ↓
Permission check
    ↓
Schema validation
    ↓
Confirmation check
    ↓
Audit intent (fail-closed)
    ↓
Deterministic Lunar tool
    ↓
Audit outcome
    ↓
PyQGIS / QGIS Processing / GDAL
    ↓
Output + provenance
```

The AI must never be treated as the authoritative executor of GIS math or arbitrary Python.
