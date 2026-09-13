# OpenRouter

Use when planning the OpenRouter AI gateway — not for implementation in M0/M1.

## When to use

* Designing future `lunar_gis/ai/` provider abstraction, structured outputs, or context assembly docs

## Must do

* Follow `AGENTS.md:2-5,10,11` — LLM is planner, QGIS owns math, provider adapters only, no secrets logged, offline deterministic.
* Read `docs/adr/ADR-0002-ai-execution-boundary.md` (validated versioned tools, no arbitrary Python) and `docs/security/SECURITY_MODEL.md` (secrets, provider allow-list, prompt injection via layer metadata, `.env` ignored).
* Document API key via `.env` / OS keyring, never committed (`root .gitignore: .env`).

## Phase gate

> **MILESTONE GATE: M5 OpenRouter AI — DO NOT implement provider/client in M0/M1.** This skill is planning/reference only until M5 milestone ADR.

## References

* `AGENTS.md`, `docs/adr/ADR-0002`, `docs/security/SECURITY_MODEL.md`, `docs/architecture/MILESTONES.md` (M5), `docs/adr/ADR-0004` (`ai` → `agent`)

## Checklist

* [ ] No `openrouter`/`openai` client code added in M0/M1
* [ ] No API key or `.env` committed
