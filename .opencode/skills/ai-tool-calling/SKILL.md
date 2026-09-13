# AI Tool Calling

Use when designing structured tool requests, schemas, or `ToolRegistry`/`ToolSpec`.

## When to use

* Editing `lunar_gis/agent/registry.py` or defining `ToolSpec(name, version, risk, handler)`
* Adding `project.list_layers` etc. before M1 validation/permission/audit

## Must do

* Follow `AGENTS.md:2-4,9` — LLM is planner, QGIS owns math, validated versioned tools, arbitrary Python disabled by default, destructive ops need confirmation.
* Read `docs/adr/ADR-0002-ai-execution-boundary.md` and `docs/security/SECURITY_MODEL.md` (schema validated, no arbitrary exec).
* Keep `risk ∈ {read,low,medium,high}` and reject unknown tools; write tests `tests/unit/test_registry.py`.

## Must not do

* Execute LLM-generated Python without explicit high-risk confirmation.

## References

* `AGENTS.md`, `docs/adr/ADR-0002`, `docs/security/SECURITY_MODEL.md`, `docs/architecture/OVERVIEW.md` execution boundary, `lunar_gis/agent/registry.py`

## Checklist

* [ ] `ToolSpec` has `name`, `version`, `risk` validated
* [ ] `pytest -q` covers duplicate/invalid risk/unknown tool
