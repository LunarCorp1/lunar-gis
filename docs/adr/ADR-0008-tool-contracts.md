# ADR-0008: Tool Contracts and Registry

- Status: Accepted
- Date: 2026-09-14
- Deciders: architect, lunar-gis maintainers
- Related: AGENTS.md:1-12, docs/adr/ADR-0002-ai-execution-boundary.md, docs/adr/ADR-0004-module-boundaries.md, docs/security/SECURITY_MODEL.md, docs/research/M1-OSS-REUSE-AUDIT.md, lunar_gis/agent/registry.py

## Context

M1-T01 identified the need for a typed, validated tool contract layer that future AI planning and GIS execution will depend on. The existing `ToolSpec(name, version, risk, handler)` and `ToolRegistry` (33 lines) were sufficient as an initial scaffold but lacked:

- Strong typing for risk levels (string-based validation)
- Structured input/output contracts with schema validation
- Execution context without secrets
- Result type that prevents exception leakage
- Version comparison/serialization

The OSS reuse audit recommended building Lunar's own tool contract (BUILD) rather than adopting external frameworks, citing AGENTS.md rules 2-4 (LLM is planner, validated versioned tools, arbitrary Python disabled).

## Decision

Implement eight public types in `lunar_gis/agent/registry.py` as the tool contract layer:

| Type | Purpose | Key Design |
|------|---------|------------|
| `ToolRisk` | Risk classification enum | `read/low/medium/high` — frozen enum, aligned with AGENTS.md risk model |
| `ToolVersion` | Semantic versioning | `major.minor.patch`, `frozen=True, order=True`, supports comparison and `to_str()`/`from_str()` |
| `ToolInput` | Validated structured input | JSON-compatible dict, schema validated at construction, rejects non-JSON values |
| `ToolOutput` | Structured tool output | JSON-compatible dict, schema validated, no implicit execution |
| `ToolExecutionContext` | Minimal execution metadata | Frozen, no secrets/credentials/iface/network, extensible for future QGIS context |
| `ToolResult` | Success/failure result | Typed error string (not exception), mutual exclusion enforced |
| `ToolSpec` | Hardened tool specification | Name dot-notation, typed version/risk, optional schemas, handler stored but never invoked |
| `ToolRegistry` | Metadata/validation infrastructure | Register/get/has/remove/names/all_specs/validate_spec/to_dict — no execute/run/invoke/call |

### Schema validation

Custom minimal schema validator supporting `type`, `properties`, `required`, `additionalProperties`, `items` — without external `jsonschema` dependency. Validated at construction time in `ToolInput` and `ToolSpec`. Output schema validation is structural only (validates schema shape, not data against schema) since output validation is the caller's responsibility.

### JSON boundary enforcement

`_reject_non_json_values` recursively walks data structures, rejecting anything not in `(str, int, float, bool, None)`. Dict keys must be strings. This prevents functions, lambdas, sets, bytes, tuples, and custom objects from crossing the contract boundary.

### Handler stored but not invoked

`ToolSpec.handler` is a `Callable[..., Any] | None` stored for future execution layers. It is never called during registration or lookup. The handler is excluded from `to_dict()` serialization.

## Alternatives considered

1. **Use `jsonschema` library** — rejected: would add a runtime dependency for schema validation that can be implemented with ~50 lines of stdlib code. The required subset (type checking, properties, required, additionalProperties, items) is small and well-defined.

2. **Use pydantic for dataclasses** — rejected: would add a runtime dependency. The frozen dataclass + `__post_init__` validation pattern achieves the same result with stdlib only.

3. **Allow handler execution in registry** — rejected: violates the separation between metadata/validation (M1) and execution (M5+). The registry must not become an executor.

4. **Use string-based risk like the original 33-line implementation** — rejected: enum provides stronger typing, IDE support, and prevents invalid risk values at the type level.

## Consequences

* Future AI planning (M5) resolves tool requests against validated `ToolSpec` schemas before execution.
* Future execution layers call `spec.handler` directly, not through the registry.
* `ToolExecutionContext` can be extended with QGIS-specific fields (iface reference, project context) in a future milestone without breaking the contract boundary.
* Schema validation is minimal and deterministic — suitable for tool-schema versioning but not a general-purpose JSON-Schema validator.
* The contract layer is QGIS-independent (no `qgis` imports) and can be tested without QGIS runtime.

## Verification

* `python -m pytest tests/unit/test_registry.py` — 98 tests, all passing
* `ruff check .` — all checks passed
* `ruff format --check .` — all files formatted
* `mypy lunar_gis/` — success, no issues
* `bandit -c pyproject.toml -r lunar_gis` — no issues
* `python -m build` — sdist + wheel built successfully
* `test_qgis_plugin_zip_structure` — passed
