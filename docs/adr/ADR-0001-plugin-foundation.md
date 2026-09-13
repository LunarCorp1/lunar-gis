# ADR-0001: QGIS Plugin Foundation

- Status: Accepted
- Date: 2026-09-13

## Decision
Lunar GIS will be implemented initially as a Python QGIS 4 plugin using PyQGIS, Qt6-compatible APIs, and QGIS Processing where appropriate.

## Rationale
QGIS provides the host GIS engine, map canvas, data providers, Processing framework, and layout/export facilities. Lunar should add orchestration, research workflow, provenance, and cartographic intelligence rather than replace QGIS.

## Consequences
- QGIS is the runtime dependency.
- The plugin must stay compatible with the targeted QGIS 4 series.
- GIS operations should prefer stable QGIS APIs over custom reimplementation.
