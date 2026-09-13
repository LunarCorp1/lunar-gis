# ADR-0003: Local Data First

- Status: Accepted
- Date: 2026-09-13

## Decision
When planning an analysis, Lunar evaluates the current QGIS project before remote data discovery.

Required data are classified as:
- AVAILABLE — directly present.
- DERIVABLE — can be calculated from present data.
- MISSING — requires an external source or user-provided dataset.

## Consequences
- Reduced bandwidth and duplicate datasets.
- Better provenance.
- User data remains the primary source of truth.
