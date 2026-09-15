# ADR-0004: Module Boundaries

- Status: Accepted
- Date: 2026-09-13
- Deciders: architect, lunar-gis maintainers
- Related: AGENTS.md:1-12, docs/architecture/OVERVIEW.md, docs/adr/ADR-0001, docs/adr/ADR-0002, docs/adr/ADR-0003, docs/security/SECURITY_MODEL.md, docs/providers/PROVIDER_CONTRACT.md, pyproject.toml

## Context

Lunar GIS was bootstrapped as a QGIS 4 plugin with a 10-module layout in `docs/architecture/OVERVIEW.md` and empty placeholder packages added in `bea4f8e` (`lunar_gis/ai`, `analysis`, `agent`, `cartography`, `data`, `project`, `provenance`, `reports`, `ui`, `utils`). Without an explicit boundary ADR, new code risks:

* circular imports (`ai` ↔ `analysis` ↔ `data`)
* putting GIS math in the LLM path (violates AGENTS.md:1,2 and ADR-0002)
* letting `ui` or `ai` fetch URLs directly (violates AGENTS.md:5, SECURITY_MODEL.md:9)
* treating empty `__init__.py` files as accidental scaffolding to be flattened

The repository assessment and QGIS smoke test (`ea8ec8d`) confirmed imports `import lunar_gis.ai` etc. work via `setuptools.packages.find` and that `test_all_bounded_modules_importable` enforces no `qgis` in placeholders. An ADR is needed to codify responsibilities and dependency direction before M1 starts.

## Decision

Keep the bounded layout as 10 regular packages with docstring-only `__init__.py` placeholders. Empty/reserved modules are intentional architectural boundaries, not unfinished code. Responsibilities and allowed dependencies are:

| Module | Responsibility | May import | Must NOT import / do |
|--------|---------------|------------|---------------------|
| `utils` | Small shared utilities, secret redaction, path safety | nothing in `lunar_gis` | QGIS, LLM, network |
| `provenance` | Dataset and workflow lineage, audit events | `utils` | QGIS GUI, AI execution, network |
| `project` | QGIS project context, `LayerSummary`, `ProjectContext` | `utils`, `qgis.core` | `agent`, `ai`, `cartography`, network |
| `data` | Local file inspection, `DataProvider` adapters (see PROVIDER_CONTRACT.md) | `provenance`, `project`, `utils`, `qgis.core` | `ai`, `cartography`, arbitrary `requests.get(url)` |
| `analysis` | Deterministic AHP/MCE, raster/vector operations (M2/M3) | `project`, `data`, `provenance`, `utils`, `qgis.core`/`processing` | `ai` for math, LLM for weights |
| `agent` | Tool registry, validation, permissions, execution, confirmation | `project`, `provenance`, `utils` | `qgis.gui`, direct GIS math, network |
| `ai` | Provider/planner contracts, prompt assembly, context synthesis (M5) | `agent`, `utils` | `qgis`, `analysis`, `data`, direct GIS execution; must preserve offline fallback (AGENTS.md:11) |
| `cartography` | Layout/style/QA engine (M7) | `analysis`, `project`, `data`, `utils`, `qgis.core` layouts | fetch URLs, LLM pixel math (AGENTS.md:1,2) |
| `reports` | Reproducible reports, markdown/html/pdf (M8) | `provenance`, `analysis`, `project`, `utils` | network, LLM as source of truth |
| `ui` | PyQt/QGIS UI, dock, dialogs | `project`, `agent`, `utils`, `qgis.PyQt` | business logic, GIS math, provider calls |

`resources/` is **not a package** (no `__init__.py`); it is package-data under `lunar_gis/resources/icon.svg` accessed via `Path(__file__).parent / "resources"` and `importlib.resources` (verified in `test_icon_accessible_via_importlib_resources`).

Top-level `processing/` is not a package and is not discovered by `tool.setuptools.packages.find`. The QGIS Processing provider lives at `lunar_gis/processing/` (introduced in M2 for AHP; extended in M3/M9 for additional algorithms).

## Alternatives considered

1. **Flat `lunar_gis/` monolith** — rejected: would hide GIS/AI/UI coupling, make `test_all_bounded_modules_importable` impossible, and invite LLM math.
2. **One package per GIS domain with immediate implementation** — rejected: violates AGENTS.md Scope discipline (`MILESTONES.md` sequential), would create premature AHP/MCE/provider code in M0.
3. **PEP 420 namespace packages (no `__init__.py`)** — rejected: `setuptools.packages.find` would not discover reserved modules, and empty dirs are untracked in git.

Chosen: 10 regular packages, discovered via `include = ["lunar_gis*"]`, each `__init__.py` contains only a docstring referencing its milestone (see `lunar_gis/ai/__init__.py` etc.).

## Consequences

* New code must respect the DAG above; circular imports (`agent` → `ui` → `agent`) will fail review and `test_all_bounded_modules_importable` (which asserts no `import qgis` in placeholders).
* `analysis`, `cartography`, `data` must use `qgis.core` / Processing for math (AGENTS.md:1); `ai` must not execute GIS.
* `data` external access must go through `DataProvider` adapters (AGENTS.md:5, SECURITY_MODEL.md:9); arbitrary URL fetch is a security violation.
* Prompts must treat `project` metadata as untrusted (`SECURITY_MODEL.md` threat: prompt injection via layer metadata).
* Until each milestone ADR is accepted, reserved modules stay docstring-only. Gate tags: `ahp-mce`→M2/M3, `data`/`stac`/`osm`→M4, `openrouter`/`ai-tool-calling`→M5, `cartography`→M7. See `.opencode/skills/*/SKILL.md` phase gates.
* Verification: `python -m pytest tests/unit/test_packaging.py::test_all_bounded_modules_importable`, `test_qgis_plugin_zip_structure`, and `git ls-files | grep lunar_gis/`; QGIS smoke test confirms package installs as `lunar_gis/` top-level ZIP.
