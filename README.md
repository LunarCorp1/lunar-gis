# Lunar GIS

AI-assisted GIS research, analysis, data discovery, provenance, and automatic cartography for QGIS 4.

## What it is

Lunar GIS is a QGIS 4 plugin that combines project understanding, deterministic data engineering, governed tool execution, AHP analysis, controlled external data, AI-assisted planning (OpenRouter), automated cartography, provenance, and reproducible reports — with QGIS owning all GIS correctness and the AI acting strictly as planner/interpreter.

Core principle: **the AI proposes; the governed tool system decides what may execute; QGIS performs the GIS work.**

## Capabilities

- **Project context** — layer inventory snapshots (geometry, CRS, fields, counts, extents, validity, snapshot identity + staleness)
- **Data engine** — structured requirements, AVAILABLE/DERIVABLE/MISSING classification, local fulfillment, controlled acquisition, QGIS-authoritative validation, declared transformations, provenance, DataResult
- **Providers** — STAC (Earth Search), OSM Overpass (bounded QL-from-enums), Nominatim (policy-compliant) behind an SSRF-safe transport (allowlist + resolved-IP blocking + redirect re-validation)
- **Transformations** — reproject-vector/raster, clip, filter, join (1:1), raster↔vector via pinned native Processing algorithms
- **GIS analysis** — buffer, intersection, dissolve, zonal statistics, spatial join (governed tools + Processing algorithms)
- **AHP + sensitivity** — deterministic weights, CI/CR, OAT perturbation, stability intervals
- **AI layer** — OpenRouter provider abstraction, trust-labeled privacy-controlled context, structured tool calling validated against the registry, offline heuristic fallback
- **Cartography** — deterministic Okabe-Ito styling, print layouts (map/title/legend/scalebar/north-arrow/provenance), QA checklist, PDF/PNG export
- **Reports** — reproducible analytical content (hashed, timestamp-free) rendered as accessible self-contained HTML
- **UI workspace** — 8-tab dock panel (Assistant/Project/Data/Analysis/Results/Provenance/Reports/Settings) with explicit HIGH-risk confirmations and offline mode

## Installation

1. Build or download `lunar_gis.zip` (`python -m build`, or CI artifacts).
2. In QGIS: `Plugins > Manage and Install Plugins > Install from ZIP`, select the ZIP.
3. Open via the Lunar GIS toolbar icon (dockable panel, right side by default).
4. Optional: set an OpenRouter API key in Settings for AI-assisted planning (everything else works offline).

Requirements: QGIS 4.x, Python ≥ 3.10. Zero runtime pip dependencies.

## Typical workflow

1. Open the workspace, refresh the project snapshot (Project tab).
2. Ask a question in Assistant, or author a requirement in Data and check it.
3. Review AVAILABLE / DERIVABLE / MISSING verdicts and evidence.
4. Confirm acquisition for provider data, or run transformations/analysis.
5. Validate results, inspect provenance, generate a map and a reproducible report.

## Product principles

- Deterministic GIS execution (QGIS authority)
- AI as planner, not calculator
- Local-data-first workflow
- Controlled external data providers
- Provenance by default
- Reproducible workflows
- Safety before automation (fail-closed, confirmations, audit)
- Professional accessible cartography

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

# type check (mypy)
mypy lunar_gis

# tests (offline deterministic; qgis-marked tests skip without QGIS)
pytest -q
# with coverage (threshold 40, single-sourced in pyproject.toml)
pytest --cov=lunar_gis --cov-report=term-missing --cov-report=xml --cov-fail-under=40 -q

# security (dev/CI only, not runtime)
bandit -c pyproject.toml -r lunar_gis
# Gitleaks via CI action gitleaks/gitleaks-action@v3.0.0 (SHA-pinned e0c47f...); local if binary installed:
# gitleaks detect --source . --no-git --verbose

# build/package verification
python -m build
pytest tests/unit/test_packaging.py::test_qgis_plugin_zip_structure -q
```

**Security:** Secrets must never be committed (see `docs/security/SECURITY_MODEL.md`). Hard-coded keys, arbitrary-URL fetching, `eval/exec` will fail `bandit`/`security-gate`. Module boundaries (`docs/adr/ADR-0004`) and the execution boundary (`docs/adr/ADR-0002`) are enforced by tests, not just scanners.

**Coverage:** threshold 40% (`fail_under` single-sourced in `pyproject.toml`); current total ~70%+ branch coverage. Do not lower the threshold.

### QGIS verification

QGIS 4.2.0 live verification covers: discovery/validation/transformation/cartography paths, all Processing algorithms, workspace construction, and plugin load. `qgis`-marked tests run under a QGIS Python with the plugin importable; CI runs the offline suite.

## Documentation

- `docs/architecture/OVERVIEW.md` — system overview
- `docs/architecture/MILESTONES.md` — milestone status
- `docs/adr/` — architecture decision records (index in `docs/adr/README.md`)
- `docs/research/M4-DATA-ENGINE-DESIGN.md` — data engine design + implementation notes
- `docs/security/SECURITY_MODEL.md` — security model
- `docs/providers/PROVIDER_CONTRACT.md` — provider contract

## Limitations

- Multi-step transformation chains beyond length 3 are rejected (v1 bound).
- No `merge`/mosaic op: tiled partials are MISSING by design (documented in M4 §8).
- Providers requiring credentials are unsupported (no vault; AUTH_REQUIRED fails closed).
- Live LLM calls never run in CI (deterministic fixtures/mocks only).
- `qgis`-marked tests skip without a QGIS runtime.

## License

GPL-2.0-or-later. See `LICENSE`.
