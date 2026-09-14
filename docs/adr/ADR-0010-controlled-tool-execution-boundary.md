# ADR-0010: Controlled Tool Execution Boundary

- Status: Accepted
- Date: 2026-09-14
- Deciders: architect, ai-security-reviewer, test-engineer, lunar-gis maintainers
- Related: AGENTS.md:1-12, docs/adr/ADR-0002-ai-execution-boundary.md, docs/adr/ADR-0004-module-boundaries.md, docs/adr/ADR-0008-tool-contracts.md, docs/adr/ADR-0009-tool-governance.md, docs/security/SECURITY_MODEL.md, lunar_gis/agent/execution.py, lunar_gis/agent/governance.py, lunar_gis/agent/registry.py

## Context

M1-T02 established the typed tool contract (`registry.py`) and M1-T03 established the governance layer (`governance.py`). The governance layer produces a `PolicyDecision` (permission + confirmation) but nothing yet executes a registered tool. The missing piece is the deterministic, non-LLM execution boundary that:

1. Resolves a registered `ToolSpec` from the `ToolRegistry`.
2. Validates input against the `ToolSpec` input schema.
3. Evaluates permission via the `PolicyEngine`.
4. Enforces confirmation via a scoped confirmation artifact.
5. Invokes the registered handler only after every governance check passes.
6. Normalizes and validates output.
7. Audits every security-relevant outcome.

Without this boundary, an AI layer could invoke handlers ad hoc and circumvent the risk/governance guarantees established in ADR-0008 and ADR-0009. The boundary is the single entry point that future AI/agent planners and QGIS-integrated tools must use to execute a registered tool.

## Decision

Create `lunar_gis/agent/execution.py` containing a `ControlledExecutor` with four public types:

| Type | Purpose |
|------|---------|
| `ConfirmationStatus` | Enum: VALID / MISSING / WRONG_TOOL / WRONG_INPUT / WRONG_CONTEXT |
| `ConfirmationArtifact` | Frozen dataclass binding explicit user confirmation to one tool invocation |
| `ControlledExecutor` | Single governed execution entry point; returns `ToolResult` |

### Execution lifecycle

The `execute()` method enforces, in order:

1. Resolve registered tool from registry
2. Validate tool metadata
3. Evaluate permission via `PolicyEngine`
4. Validate input against `ToolSpec` input schema
5. Evaluate confirmation requirement
6. Verify confirmation artifact (if required)
7. Write intent audit record BEFORE invoking the handler (fail-closed)
8. Invoke registered handler
9. Normalize output into `ToolOutput`
10. Validate output against `ToolSpec` output schema
11. Produce `ToolResult`
12. Write terminal audit record (success or failure)

### Confirmation artifacts are scoped, not single-use tokens

A `ConfirmationArtifact` is a SHA-256 fingerprint over `tool_name + tool_version + canonical input JSON + canonical execution-context JSON`. It is bound to exactly one invocation. It is NOT reusable for a different tool, version, input, or context. It contains no secrets.

This is deliberately NOT a cryptographic one-time token: an artifact represents "the user reviewed and approved this exact invocation." Single-use revocation and time-based expiry are deferred to a future milestone for higher-risk tools (see ADR-0009, alternatives item 4).

### Audit is fail-closed and never raises

The intent audit record is written before the handler is invoked. If the intent record cannot be written, the handler is never invoked and `execute()` returns a failed `ToolResult`. Terminal audit records (success/failure) are written after the outcome is known; a terminal-audit failure after a successful handler is surfaced as a failed `ToolResult` rather than an unhandled exception.

Audit-sink failures never raise out of `execute()`: every path returns a structured `ToolResult`. `AuditRecord` now includes an optional `error` field so security-relevant reasons ("permission denied", "confirmation required but absent or invalid", "unknown tool") are preserved in the audit trail, not dropped.

### Permission precedes input validation

Permission is evaluated before value-level input validation. This ensures that an input-validation failure (a violation attempt) still produces a `PolicyDecision` so an audit record can be written. Before this decision, an invalid input would skip auditing entirely.

### Execution outcome classification deferred

`ToolResult.success` is the outcome signal for M1. A dedicated outcome enum was considered but rejected as dead API for this milestone; classification at the consumer/UI layer can be added later without changing the boundary contract.

## Alternatives considered

1. **Audit after execution only** — rejected: a handler interrupted mid-run by a hard failure (process death, `KeyboardInterrupt`) would leave no record of a tool that executed. Fail-closed intent auditing closes this gap.

2. **Redundant decision after output validation** — rejected: the success path already carries the `PolicyDecision`; re-evaluating after execution adds no governance value and introduces a TOCTOU surface.

3. **Dedicated outcome enum on `ToolResult`** — rejected for M1: `success: bool` plus `error` covers every current path; an enum adds public surface with no consumer yet.

4. **Confirmation artifact as single-use cryptographic token** — rejected for M1: interface changes would break the governance contract; the fingerprint-scoped artifact satisfies the "explicit user approval for this exact invocation" requirement today.

## Consequences

* All handler execution flows through one governed entry point — no ad hoc invocation path for AI planners or third-party code.
* Fail-closed intent auditing guarantees an audit record exists before any handler executes; sink failure blocks execution.
* DENY still cannot be overridden by confirmation, and ALLOW without required confirmation is blocked (both enforced and tested).
* The module is pure stdlib and QGIS-free — it runs in CI without a QGIS runtime and preserves offline determinism (AGENTS.md rule 11).
* `AuditRecord.error` and `ConfirmationStatus.WRONG_CONTEXT` are additive contract extensions; existing governance tests remain valid.
* ADR-0009 item 4 "future executor" is now fulfilled; ADR-0009 remains immutable as the historical decision record.

## Verification

* `python -m pytest tests/unit/test_execution.py` — 61 tests, all passing
* `python -m pytest tests/unit/test_governance.py` — 70 tests, all passing (no regression)
* `python -m pytest tests/unit/test_registry.py` — 98 tests, all passing (no regression)
* `ruff check .` — all checks passed
* `ruff format --check .` — all files formatted
* `mypy lunar_gis/` — success, no issues
* `pytest --cov=lunar_gis --cov-fail-under=40` — 82.70% total coverage; `execution.py` at 97%
* `bandit -c pyproject.toml -r lunar_gis` — no issues
* `python -m build` — sdist + wheel built successfully
* `test_qgis_plugin_zip_structure` — passed