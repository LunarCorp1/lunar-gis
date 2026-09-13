# PyQGIS

Use when writing deterministic GIS code with `qgis.core` / `QgsProject` / `QgsVectorLayer`.

## When to use

* Editing `lunar_gis/project/context.py` (`LayerSummary`, `ProjectContext`) or future `lunar_gis/analysis/` / `data` GIS operations
* Inspecting CRS, geometry type, feature count, extent

## Must do

* Follow `AGENTS.md:1,2,7,11` — QGIS owns math, LLM is planner, distinguish AVAILABLE/DERIVABLE/MISSING, preserve offline deterministic.
* Read `docs/adr/ADR-0001-plugin-foundation.md` and `docs/architecture/OVERVIEW.md` before adding GIS logic.
* Stay on GUI thread for `QgsProject.instance()` / `QgsVectorLayer` access; no threading without `QgsTask` + ADR.
* Write tests with fakes (`tests/conftest.py` `FakeLayer`/`FakeProject`) for `geometryType()`, `featureCount()`, `crs().authid()` branches (see `docs/security/SECURITY_MODEL.md` for untrusted metadata handling).

## Must not do

* Let LLM calculate GIS math — use deterministic `qgis.core` / Processing.

## References

* `AGENTS.md`, `docs/adr/ADR-0001-plugin-foundation.md`, `docs/architecture/OVERVIEW.md`, `lunar_gis/project/context.py`, `docs/security/SECURITY_MODEL.md`

## Checklist

* [ ] All `qgis.core` calls guarded with `hasattr`/`try` for raster vs vector
* [ ] No network or LLM call in GIS path
