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
pytest --cov=lunar_gis --cov-report=term-missing --cov-report=xml --cov-fail-under=20 -q

# build/package verification
python -m build
pytest tests/unit/test_packaging.py::test_qgis_plugin_zip_structure -q
```

Complete local gate (same as CI):

```bash
ruff check . && ruff format --check . && mypy lunar_gis && pytest --cov=lunar_gis --cov-report=term-missing --cov-fail-under=20 -q && python -m build
```

**Coverage baseline:** 24% total (23.61% branch) measured 2026-09-14 at `3ba4667` (122 stmts, 22 branches, `lunar_gis/__init__.py` 33%, `agent/registry.py` 92% branch, `project/context.py` 24% branch, `plugin.py` 0% — not yet covered, will rise in P0-T08). Threshold `fail_under = 20` is intentionally below baseline to prevent silent regression without demanding artificial tests; raise defensibly after P0-T08 (target 40-60%). `fail_under` is single-sourced in `pyproject.toml:fail_under` and mirrored in CI/README — do not lower.

## License

GPL-2.0-or-later. See `LICENSE`.
