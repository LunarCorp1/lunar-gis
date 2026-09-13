# ADR-0005: Build and Toolchain

- Status: Accepted
- Date: 2026-09-13
- Deciders: architect, lunar-gis maintainers
- Related: AGENTS.md:1-12, ADR-0001, ADR-0004, pyproject.toml, lunar_gis/__version__.py, lunar_gis/metadata.txt, docs/security/SECURITY_MODEL.md, tests/unit/test_packaging.py

## Context

After `bea4f8e` the plugin needed reproducible packaging for both `pip` (sdist/wheel) and QGIS Plugin Manager (ZIP with `lunar_gis/` top-level), single-source versioning, and correct GPL distribution. The toolchain must work for source checkout, `pip install -e .`, built distributions, and the QGIS ZIP validated manually on Windows QGIS 4.0.1. Empty `lunar_gis/*` modules also needed discovery without flat-list drift.

## Decision

Record the toolchain as implemented and verified:

| Area | Decision | Key file / evidence |
|------|----------|---------------------|
| **Python compat** | `requires-python >=3.10` (QGIS 4 bundles 3.12, CI currently 3.14, QGIS minimum 4.0) — floor stays 3.10 for CI breadth, not 3.12, to keep `str | None` syntax valid since 3.10 | `pyproject.toml:10`, `tests` run 3.14 |
| **Build backend** | `setuptools>=80` `setuptools.build_meta` | `pyproject.toml:2` — required for `project.license-files` + `License-Expression` (PEP 639) |
| **Package discovery** | `include = ["lunar_gis*"]` via `tool.setuptools.packages.find` (replaces flat `packages = ["lunar_gis"]`) | `pyproject.toml:19`, `test_pyproject_package_discovery` |
| **Dynamic version** | Single source `lunar_gis/__version__.py:3` `__version__ = "0.1.0"` → `project.dynamic = ["version"]` + `tool.setuptools.dynamic.version.attr = "lunar_gis.__version__.__version__"` | `test_version_single_source`, `test_installed_version_matches_metadata` |
| **QGIS packaging** | `lunar_gis/` is the plugin root for ZIP; `package-data` `lunar_gis = ["metadata.txt","resources/*","LICENSE*"]` | `test_qgis_plugin_zip_structure` |
| **Resources** | Filesystem `lunar_gis/resources/icon.svg` resolved via `Path(__file__).resolve().parent / "resources" / "icon.svg"` `lunar_gis/plugin.py:20` and `importlib.resources.files` — no `pyrcc`/`resources.qrc` (deleted `bea4f8e`, Option B) | `test_icon_exists_packaged_location`, `test_icon_accessible_via_importlib_resources` |
| **Metadata** | Canonical `lunar_gis/metadata.txt` byte-equal to repo `metadata.txt` (`test_metadata_exists_canonical_and_root_sync`), `icon=resources/icon.svg`, `qgisMinimumVersion=4.0`, `version` matches `__version__` | `test_metadata_*` |
| **Licensing** | `project.license = "GPL-2.0-or-later"` SPDX string + `project.license-files = ["LICENSE*"]` + dual `LICENSE`/`lunar_gis/LICENSE` byte-equal GPL-2.0 (Franklin address) | `METADATA` `License-Expression: GPL-2.0-or-later`, `License-File: LICENSE` |
| **Dev vs QGIS runtime** | Dev: `pip install -e .` + `python -m pytest -q` + `python -m build`; QGIS: `dist/lunar_gis.zip` installed via `Plugins > Install from ZIP` on Windows QGIS 4.0.1 (manual smoke `dist/lunar_gis.zip` 12444B) | `dist/lunar_gis-0.1.0-py3-none-any.whl` 21827B, smoke report 2026-09-13 |
| **OpenCode toolchain** | `@opencode-ai/plugin@1.18.30` Node `package.json` local, `node_modules` ignored (see `.opencode/.gitignore`) | `.opencode/package.json` |

`__pycache__/`, `build/`, `dist/`, `*.egg-info/`, `.pytest_cache/` remain ignored; `LICENSE` is included via both `license-files` (top-level for PyPI) and `package-data` (inside package for QGIS).

## Alternatives considered

* **Static `project.version = "0.1.0"`** — rejected: would duplicate `metadata.txt` version and `__version__.py`, drift already flagged by `test_version_single_source` substring guard.
* **`packages = ["lunar_gis"]` flat list** — rejected: would omit `lunar_gis.agent`, `lunar_gis.project` and 8 reserved modules from wheel.
* **`pyrcc` Qt resources** (`resources.qrc` → `resources_rc.py`) — rejected: extra `pyrcc6` build step, Qt6 SVG via filesystem `QIcon` is sufficient and tested.
* **`setuptools<80` / `license = {text=...}`** — rejected: deprecated `License:` field, missing `License-Expression`, fails PEP 639 `Metadata-Version: 2.4`.

## Consequences

* Version bump is edit of `lunar_gis/__version__.py` only; `metadata.txt` files and `importlib.metadata.version("lunar-gis")` follow via dynamic attr and byte-equality test.
* Empty modules stay importable (`import lunar_gis.ai`) and appear in sdist/wheel and QGIS ZIP without code.
* Dual LICENSE ensures `pip` (`dist-info/licenses/LICENSE`) and QGIS (`lunar_gis/LICENSE`) satisfy GPL §1 and `plugins.qgis.org` reviewer.
* Build remains reproducible: `python -m build` + `twine check` + `pytest` gate in `.github/workflows/ci.yml` (currently `pytest -q` on 3.11; future add `python -m build` smoke).
* No redesign: future milestones keep this toolchain; any change (e.g., ruff/mypy, `requires-python` bump) needs a new ADR.
