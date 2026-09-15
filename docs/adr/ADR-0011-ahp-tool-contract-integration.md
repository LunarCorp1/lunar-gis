# ADR-0011: AHP Tool Contract & Registry Integration

- Status: Accepted
- Date: 2026-09-15
- Deciders: architect, ai-security-reviewer, test-engineer, lunar-gis maintainers
- Related: AGENTS.md:1-12, docs/adr/ADR-0004-module-boundaries.md, docs/adr/ADR-0008-tool-contracts.md, docs/adr/ADR-0009-tool-governance.md, docs/adr/ADR-0010-controlled-tool-execution-boundary.md, docs/research/M2-AHP-METHODOLOGY-AND-OSS-AUDIT.md, lunar_gis/analysis/ahp.py, lunar_gis/analysis/tools.py, lunar_gis/agent/registry.py, lunar_gis/agent/execution.py

## Context

M2-T02 implemented the deterministic AHP core engine (`lunar_gis/analysis/ahp.py`) with a pure-stdlib mathematical API (`ahp()` → `AHPResult`). M1 established the Tool Contract (`registry.py`), governance (`governance.py`), and ControlledExecutor (`execution.py`). The missing piece is the thin adapter that connects the AHP engine to the M1 tool boundary so that:

1. AHP is available as a registered tool with explicit input/output schemas.
2. The complete governed execution path (permission → confirmation → audit → handler → audit) works for AHP.
3. AHP errors map cleanly across the tool boundary without losing diagnostic information.
4. The AHP engine remains the mathematical source of truth — the adapter does not reimplement any calculation.

The `agent→analysis` edge was flagged in M2-T01 §17 as requiring an ADR assessment.

## Decision

Create `lunar_gis/analysis/tools.py` containing:

| Component | Purpose |
|-----------|---------|
| `AHP_INPUT_SCHEMA` | JSON Schema for `ToolInput`: `criteria` (array of strings) + `matrix` (array of arrays of numbers) |
| `AHP_OUTPUT_SCHEMA` | JSON Schema for `ToolOutput`: weights, lambda_max, ci, ri, cr, flag, provenance fields |
| `AHP_TOOL_SPEC` | `ToolSpec` with name `analysis.ahp`, version `1.0.0`, risk `LOW` |
| `ahp_handler()` | Thin adapter: `ToolInput` → `ahp()` → `ToolOutput` dict |
| `register_ahp_tool()` | Convenience to register the AHP tool with its handler |

### Risk classification: LOW

AHP is purely computational. It does not:
- modify external data
- access the network
- write to the filesystem
- execute arbitrary code
- access QGIS GUI

The default `ConfirmationPolicy` does not require confirmation for `LOW` risk tools (ADR-0009). This is appropriate because AHP produces mathematical results with no side effects.

### Error mapping

`AHPError` (with stable `AHPErrorCode`) propagates through the handler. The `ControlledExecutor` catches exceptions and converts them to failed `ToolResult` with the error message preserved (execution.py line 328). The `AHPErrorCode` string is included in the error message, enabling callers to distinguish error types without the adapter needing to translate error codes.

### Consistency handling

The M2-T02 consistency classification (`ACCEPTABLE`, `ACCEPTABLE_WITH_WARNING`, `REVISE_REQUIRED`) is preserved exactly in the output. The adapter does not filter, suppress, or reinterpret `REVISE_REQUIRED`. Downstream policy enforcement belongs outside the mathematical engine.

### Module boundary

Per ADR-0004, `analysis` may import `project`, `data`, `provenance`, `utils`, and `qgis.core`/`processing`. The adapter imports from `agent` (for `ToolSpec`, `ToolRegistry`, etc.) and from `analysis.ahp` (for the engine). This is the first `agent→analysis` dependency edge.

The dependency direction is:

```
agent (ToolSpec/ToolRegistry) ← analysis/tools.py → analysis/ahp.py
```

The adapter is in `analysis/tools.py`, not in `agent/`, because:
1. It belongs to the analysis module's responsibility (AHP tool boundary).
2. The `agent` module must not import from `analysis` (ADR-0004: `agent` imports `project`, `provenance`, `utils`).
3. The adapter imports from `agent` for contract types — this is the allowed direction.

### No ADR amendment to ADR-0004

ADR-0004 permits `analysis` to import `project`, `data`, `provenance`, `utils`, and `qgis.core`/`processing`. It does not explicitly list `agent` as an allowed import for `analysis`. However, the adapter is a thin integration boundary that:
- imports only typed contracts from `agent` (ToolSpec, ToolRegistry, ToolInput, ToolOutput, ToolResult, ToolRisk, ToolVersion)
- does not import governance or execution internals
- is the natural location for the analysis-tool boundary

This does not require an ADR amendment because:
1. The adapter is a boundary file, not business logic in `agent`.
2. The dependency direction (`analysis` → `agent` for contracts) does not create circular imports.
3. ADR-0004's DAG already implies that analysis-tool adapters live in `analysis`.

## Alternatives considered

1. **Put adapter in `agent/`** — rejected: would create `agent` → `analysis` dependency, violating ADR-0004.

2. **Put adapter in a new `lunar_gis/integrations/` package** — rejected: unnecessary complexity for one adapter; the analysis module owns AHP.

3. **Register AHP directly in `agent/`** — rejected: handler registration must not couple `agent` to `analysis` internals.

4. **Use MEDIUM risk to require confirmation** — rejected: AHP has no side effects; requiring confirmation for a pure computation would be excessive and would break the default policy semantics.

## Consequences

* AHP is available through the standard governed execution path.
* The AHP engine remains the sole source of mathematical truth — the adapter is a thin translator.
* `AHPError` codes propagate through the tool boundary, preserving diagnostic information.
* Consistency classification is preserved exactly — no silent conversion of `REVISE_REQUIRED`.
* The adapter does not introduce QGIS, network, filesystem, or arbitrary execution capabilities.
* ADR-0004 module boundaries are respected (adapter lives in `analysis`, imports contracts from `agent`).
* No new dependencies introduced.

## Verification

* `python -m pytest tests/unit/test_analysis_tools.py` — integration tests for tool registration, handler, error mapping, governed execution
* `python -m pytest tests/unit/test_ahp.py` — 69 tests, no regression
* `ruff check .` — all checks passed
* `ruff format --check .` — all files formatted
* `mypy lunar_gis/` — success, no issues
* `bandit -c pyproject.toml -r lunar_gis` — no issues
* `python -m build` — sdist + wheel built successfully
