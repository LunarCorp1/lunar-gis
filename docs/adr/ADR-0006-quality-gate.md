# ADR-0006: Quality Gate (ruff / mypy / coverage)

- Status: Accepted
- Date: 2026-09-14
- Deciders: architect, test-engineer, lunar-gis maintainers
- Related: AGENTS.md:1-12, docs/adr/ADR-0004-module-boundaries.md, docs/adr/ADR-0005-build-toolchain.md, pyproject.toml, .github/workflows/ci.yml, tests/unit/test_packaging.py

## Context

After `3ba4667` (P0-T05) the foundations (packaging, versioning, module boundaries, ADRs, skills, GPL licensing, QGIS 4.0.1 smoke via `dist/lunar_gis.zip`) were manually verified, but `pytest -q` was the only automated gate. Without lint, type, and coverage gates, regressions in the 10-module DAG or packaging could merge silently before M1 (`MILESTONES.md: M1 Project Context + Tool Registry`).

## Decision

Add a reproducible quality gate, documented as the single source for local/CI parity:

| Area | Decision | Evidence |
|------|----------|----------|
| **Ruff** | `ruff>=0.8` `select = ["E","F"]` `target-version = py310` `line-length = 120` `exclude = ["build","dist",".opencode",".pytest_cache",".venv","htmlcov","lunar_gis.egg-info"]` + `format quote-style double` | `pyproject.toml:42`, `ruff check .` + `ruff format --check .` clean on `3ba4667` after removing unused `sys` in `test_packaging.py` |
| **Mypy** | `mypy>=1.10` `python_version = 3.10` `ignore_missing_imports = false` + override `qgis.*` `ignore_missing_imports = true`, `warn_return_any = true`, `exclude = "build|dist|\\.opencode|\\.venv|..."` — only `qgis.*` silenced, not all third-party typos | `pyproject.toml:54`, `mypy lunar_gis` `Success: no issues found in 15 source files` |
| **Coverage** | `pytest-cov>=5` `source = ["lunar_gis"]` `branch = true` `omit = ["*/tests/*"]` `fail_under = 20` (single-sourced in `pyproject.toml`, mirrored in CI/README). Baseline `24%` branch (`23.61%`) measured 2026-09-14 at `3ba4667` (122 stmts, 22 branches) — intentionally below baseline to avoid artificial `plugin.py` tests; raise to 40-60 after P0-T08 Fakes | `pyproject.toml:66`, `pytest --cov --cov-fail-under=20` |
| **Pytest markers** | `unit/integration/qgis` with `--strict-markers --strict-config` | `pyproject.toml:26`, `tests` remain `16` offline unit tests |
| **Dev deps** | `project.optional-dependencies.dev = [build,mypy,pytest,pytest-cov,ruff]` dev-only, runtime empty | `pyproject.toml:15` |
| **CI** | `quality-gate` job on `ubuntu-latest` `python 3.10` (aligns `requires-python >=3.10`): `pip install -e .[dev]` → `ruff check` → `ruff format --check` → `mypy lunar_gis` → `pytest --cov ... --cov-fail-under=20` → `python -m build` → `pytest test_qgis_plugin_zip_structure` | `.github/workflows/ci.yml` |

Single source for `fail_under` is `pyproject.toml`; CI/README mirror it but must not diverge.

## Alternatives considered

* **No gate / keep `pytest -q` only** — rejected: would miss import, formatting, type, and coverage regressions before M1.
* **Ruff `select = ["E","F","I","UP","BLE"...]`** — rejected: would flag 19 existing issues (`I001` import sort, `UP035` `collections.abc`, `BLE001` blind `except Exception` in `project/context.py` defensive QGIS guards) and create churn; minimal `E/F` keeps baseline clean.
* **`mypy ignore_missing_imports = true` globally** — rejected: would hide typo'd non-QGIS imports; narrowed to `qgis.*` override only.
* **Coverage `fail_under = 50`** — rejected: would fail current `24%` baseline (needs `plugin.py` 0% covered) and force artificial tests.
* **`QGIS GUI container` in this task** — deferred to later runtime gate per P0-T07 constraints.

## Consequences

* Local `ruff check . && ruff format --check . && mypy lunar_gis && pytest --cov --cov-fail-under=20 -q && python -m build` reproduces CI; documented in `README.md: Quality gate`.
* Coverage will rise defensibly after `P0-T08` (FakeLayer/FakeProject) without lowering threshold; ADR-0005 toolchain table is extended by this gate.
* Any `requires-python` or gate change needs a new ADR per `docs/adr/README.md` lifecycle.
