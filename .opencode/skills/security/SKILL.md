# Security

Use when touching secrets, downloads, archives, tool execution, or logs.

## When to use

* Handling API keys, `.env`, `QgsMessageLog`, provider downloads, `zip` extraction, `ToolRegistry`

## Must do

* Follow `AGENTS.md:4,5,8,9,10` and `docs/security/SECURITY_MODEL.md` — no hard-coded keys, secrets never logged, downloads via provider adapters only, archives untrusted, no binary exec, destructive ops need confirmation, `tool requests` schema-validated, arbitrary Python disabled.
* Treat layer names, CRS authids, and downloaded metadata as untrusted (prompt injection). Sanitize before LLM context.
* Reference `docs/adr/ADR-0002-ai-execution-boundary.md` before adding any `agent` / `ai` tool.
* Ensure `.env` is ignored (`root .gitignore: .env, !.env.example`).

## Must not do

* `requests.get(arbitrary_url)` outside `data/DataProvider`, `eval/exec`, logging secrets.

## References

* `AGENTS.md`, `docs/security/SECURITY_MODEL.md`, `docs/adr/ADR-0002-ai-execution-boundary.md`, `docs/providers/PROVIDER_CONTRACT.md`, `lunar_gis/agent/registry.py`

## Checklist

* [ ] `git check-ignore -v .env` ignored, `.env.example` not ignored
* [ ] No `eval`, `exec`, `pickle`, or raw `urllib` in new code
