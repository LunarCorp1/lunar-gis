# QGIS 4

Use when touching QGIS 4 / Qt6 compatibility, `qgisMinimumVersion`, or Qt enums.

## When to use

* Modifying `lunar_gis/plugin.py` dock/action code or `lunar_gis/project/context.py` layer inspection
* Updating `qgisMinimumVersion` / `qgisMaximumVersion` in `lunar_gis/metadata.txt`

## Must do

* Follow `AGENTS.md:1` — prefer stable QGIS APIs over custom reimplementation.
* Use `qgis.PyQt` shim (`from qgis.PyQt.QtCore import Qt`, `QtGui.QIcon`, `QtWidgets.QDockWidget`) and Qt6 scoped enums `Qt.DockWidgetArea.AllDockWidgetAreas` / `RightDockWidgetArea` (not Qt5 flat `Qt.RightDockWidgetArea`).
* Read `docs/adr/ADR-0001-plugin-foundation.md` and `docs/architecture/OVERVIEW.md` execution boundary before adding Processing or GUI code.
* Keep `requires-python >=3.10` compatible with QGIS 4.0.1 bundled Python 3.12; test with `pytest -q` without QGIS mocked.

## Must not do

* Introduce `PyQt6` direct import bypassing `qgis.PyQt`.
* Use obsolete QGIS 3-only APIs without ADR justification.

## References

* `AGENTS.md`, `docs/adr/ADR-0001-plugin-foundation.md`, `docs/architecture/MILESTONES.md` (M0-M1), `lunar_gis/plugin.py`

## Checklist

* [ ] No `Qt.RightDockWidgetArea` substring remains
* [ ] `metadata.txt` `qgisMinimumVersion` still `4.0` unless ADR approved
