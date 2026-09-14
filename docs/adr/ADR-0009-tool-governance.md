# ADR-0009: Tool Governance Layer

- Status: Accepted
- Date: 2026-09-14
- Deciders: architect, lunar-gis maintainers
- Related: AGENTS.md:1-12, docs/adr/ADR-0002-ai-execution-boundary.md, docs/adr/ADR-0004-module-boundaries.md, docs/adr/ADR-0008-tool-contracts.md, docs/security/SECURITY_MODEL.md, lunar_gis/agent/governance.py, lunar_gis/agent/registry.py

## Context

M1-T02 established the typed tool contract (ToolSpec, ToolRegistry, ToolInput, ToolOutput, ToolRisk, ToolVersion, ToolExecutionContext, ToolResult) in `registry.py`. The next governance concern is: given a validated ToolSpec and execution context, should this invocation be permitted, and does it require explicit user confirmation?

Without a governance layer, the future executor would have no deterministic policy infrastructure to consult. Permission and confirmation would be ad-hoc, hard to audit, and impossible to test in isolation.

## Decision

Create a governance layer in `lunar_gis/agent/governance.py` with six public types:

| Type | Purpose |
|------|---------|
| `PermissionDecision` | Enum: ALLOW / DENY with deterministic reason |
| `ConfirmationDecision` | Enum: NOT_REQUIRED / REQUIRED |
| `PolicyDecision` | Combined frozen dataclass (permission + confirmation + reason + tool identity + risk) |
| `AuditRecord` | Structured metadata record for security-relevant decisions |
| `AuditSink` | Protocol for audit storage (future persistence layers implement this) |
| `InMemoryAuditSink` | In-memory implementation for testing and M1 scope |

Plus three policy classes:

| Class | Responsibility |
|-------|---------------|
| `PermissionPolicy` | Evaluates ToolSpec risk against allowed-risk configuration |
| `ConfirmationPolicy` | Evaluates ToolSpec risk against confirmation-required configuration |
| `PolicyEngine` | Composes permission + confirmation policies into a combined decision |

### Permission and confirmation are separate concerns

A tool can be:
- Permitted without confirmation (READ, LOW by default)
- Permitted but requiring confirmation (MEDIUM, HIGH by default)
- Denied

The `PolicyDecision` carries both fields as independent attributes. Permission=ALLOW does not imply confirmation has occurred. Confirmation=REQUIRED does not imply permission was granted.

### DENY cannot be overridden by confirmation

The `PolicyEngine` evaluates permission first. If DENY, the confirmation policy is never consulted. The returned `PolicyDecision` has `confirmation=NOT_REQUIRED`, making it structurally impossible for confirmation to override a denial.

### Audit is not telemetry

`AuditRecord` captures security-relevant decisions (event type, timestamp, tool identity, risk, permission, confirmation, reason, session ID). It does not log API keys, credentials, raw inputs, datasets, or project contents. The `AuditSink` protocol is append-only — no push/telemetry/streaming semantics.

### Default risk policy

| Risk | Permission | Confirmation |
|------|-----------|-------------|
| READ | ALLOW | NOT_REQUIRED |
| LOW | ALLOW | NOT_REQUIRED |
| MEDIUM | ALLOW | REQUIRED |
| HIGH | ALLOW | REQUIRED |

Both policies are configurable via `frozenset[ToolRisk]` parameters.

## Alternatives considered

1. **Single boolean decision** — rejected: collapses permission and confirmation into one concept, making it impossible to represent "permitted but needs confirmation" or "denied regardless of confirmation."

2. **Hardcoded risk thresholds** — rejected: the governance layer must be configurable for future policy variations (e.g., read-only mode, elevated privileges) without code changes.

3. **Persistent audit database** — rejected for M1: adds complexity without value before the executor exists. The `AuditSink` protocol makes persistence a future orthogonal concern.

4. **Cryptographic confirmation tokens** — rejected for M1: premature. The architecture can add tokens at the executor/UI layer without breaking the governance contract.

## Consequences

* The future executor consumes `PolicyDecision` — it checks `permission` and `confirmation` before calling `spec.handler`.
* Policy evaluation is pure/deterministic — testable without QGIS runtime, network, or GUI.
* `AuditSink` protocol enables future persistence (database, file, remote) without modifying the governance layer.
* The governance layer has zero QGIS imports — it remains in the agent module's allowed-import scope per ADR-0004.
* `PolicyEngine.audit()` uses `time.time()` for timestamps — acceptable for M1; injectable clock can be added later for deterministic testing.

## Verification

* `python -m pytest tests/unit/test_governance.py` — 68 tests, all passing
* `python -m pytest tests/unit/test_registry.py` — 98 tests, all passing (no regression)
* `ruff check .` — all checks passed
* `ruff format --check .` — all files formatted
* `mypy lunar_gis/` — success, no issues
* `bandit -c pyproject.toml -r lunar_gis` — no issues
* `python -m build` — sdist + wheel built successfully
* `test_qgis_plugin_zip_structure` — passed
