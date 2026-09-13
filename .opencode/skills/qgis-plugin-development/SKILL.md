# QGIS Plugin Development

Use when creating or modifying the QGIS plugin shell, packaging, or lifecycle.

## When to use

* Editing `lunar_gis/__init__.py:4` `classFactory`, `lunar_gis/plugin.py`, `lunar_gis/metadata.txt`, `lunar_gis/resources/icon.svg`
* Changing `pyproject.toml` packaging or `lunar_gis/__version__.py`
* QGIS Plugin Manager install / ZIP structure checks

## Must do

* Follow `AGENTS.md:1-11` — QGIS/PyQGIS owns GIS execution; preserve offline deterministic functionality.
* Read `docs/adr/ADR-0001-plugin-foundation.md` and `docs/adr/ADR-0005-build-toolchain.md` before changing toolchain.
* Verify current QGIS 4 / Qt6 APIs via project docs, not model memory.
* Keep `lunar_gis/metadata.txt` byte-equal to `metadata.txt` and `lunar_gis/__version__.py` in sync (`tests/unit/test_packaging.py: test_metadata_*`, `test_version_single_source`).
* Use `Path(__file__).resolve().parent / "resources" / "icon.svg"` for icon, not `parent.parent`; test via `test_plugin_resolves_resource_via_parent` and `importlib.resources`.

## Must not do

* Add AI, provider, or analysis code to the shell.

## References

* `AGENTS.md`, `docs/architecture/OVERVIEW.md`, `docs/adr/ADR-0001`, `docs/adr/ADR-0005`, `lunar_gis/plugin.py`, `tests/unit/test_packaging.py`

## Checklist

* [ ] `pip install -e . && python -m pytest -q` passes
* [ ] `python -m build && unzip -l dist/*.whl` shows `lunar_gis/metadata.txt` + `resources/icon.svg` + `LICENSE`
* [ ] Manual QGIS `Install from ZIP` still works (if packaging changed)
