# Lunar GIS

AI-powered GIS research, analysis, data discovery, provenance, and automatic cartography for QGIS 4.

## Current status

Foundation phase. The current implementation target is a minimal QGIS plugin shell with project/layer context and the beginning of a safe tool-registry architecture.

## Product principles

- Deterministic GIS execution
- AI as planner, not calculator
- Local-data-first workflow
- Controlled external data providers
- Provenance by default
- Reproducible workflows
- Safety before automation
- Professional cartography

## Development

Development is performed with OpenCode. See `AGENTS.md` and `.opencode/`.

### Quality gate

The project uses a reproducible quality gate (see `pyproject.toml` and `.github/workflows/ci.yml`):

```bash
# install with dev tools
pip install -e .[dev]

# lint (Ruff) — E/F rules, Python 3.10, 120 char line
ruff check .
ruff format --check .

# type check (mypy) — ignore_missing_imports for qgis.*
mypy lunar_gis

# tests (offline deterministic, no QGIS)
pytest -q
# with coverage (threshold documented below)
pytest --cov=lunar_gis --cov-report=term-missing --cov-report=xml --cov-fail-under=40 -q

# build/package verification
python -m build
pytest tests/unit/test_packaging.py::test_qgis_plugin_zip_structure -q
```

Complete local gate (same as CI):

```bash
ruff check . && ruff format --check . && mypy lunar_gis && pytest --cov=lunar_gis --cov-report=term-missing --cov-fail-under=40 -q && python -m build
```

**Coverage baseline:** 44% total (44.44% branch) measured 2026-09-14 at `3e34a10` + `P0-T08` fakes (122 stmts, 22 branches, `lunar_gis/__init__.py` 33%, `agent/registry.py` 100%, `project/context.py` 100%, `plugin.py` 0% — still not covered, will rise only with QGIS harness). Previous baseline at `3ba4667` was 24% (23.61% branch). Threshold raised from `20` → `40` defensibly after covering `project/context` defensive branches and `registry` sorted/unknown-tool paths with meaningful tests (not artificial); next raise target 50-60 after future harness can cover `plugin.py`. `fail_under` is single-sourced in `pyproject.toml:fail_under` and mirrored in CI/README — do not lower.

## License

GPL-2.0-or-later. See `LICENSE`.
