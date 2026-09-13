# Lunar GIS — OpenCode Engineering Rules

## Mission
Lunar GIS is a QGIS 4 plugin for AI-assisted GIS research, data discovery, deterministic spatial analysis, automated cartography, provenance, and reproducible workflows.

## Non-negotiable architecture rules
1. QGIS/PyQGIS/Processing owns GIS execution and mathematical correctness.
2. The LLM is a planner/interpreter, never the source of truth for GIS calculations.
3. AI requests must resolve to validated, versioned tools/schemas before execution.
4. Arbitrary AI-generated Python execution is disabled by default and requires explicit high-risk confirmation.
5. External data access must go through provider adapters; never let the model fetch arbitrary URLs directly.
6. Existing local/project data takes priority over external downloads.
7. Distinguish AVAILABLE, DERIVABLE, and MISSING data.
8. Data transformations and external datasets must have provenance metadata.
9. Destructive operations and meaningful downloads require explicit confirmation.
10. Never log secrets, API keys, access tokens, or sensitive local data.
11. Preserve offline deterministic GIS functionality when AI/network access is unavailable.
12. Do not copy external open-source code without reviewing license and dependency obligations.

## OpenCode workflow
For every non-trivial feature:
1. Read relevant skills before implementation.
2. Inspect existing architecture and tests.
3. Plan the smallest coherent change.
4. Implement.
5. Run targeted tests.
6. Run the full available quality gate.
7. Request independent specialist review when applicable.
8. Fix review findings.
9. Re-run affected tests and quality gates.
10. Update documentation/ADR when architecture changes.

Never skip review or quality gates merely because a change appears simple.

## Review expectations
Use specialist agents for independent review where applicable:
- architect
- qgis-expert
- gis-methodology-reviewer
- ai-security-reviewer
- cartography-reviewer
- data-engineer
- test-engineer
- dependency-license-auditor
- documentation-reviewer

Review agents should be read-only unless explicitly assigned implementation work.

## Scope discipline
Do not implement future-phase features opportunistically. The current milestone is the plugin foundation and safe project/layer context/tool registry. Do not add OpenRouter, data providers, AHP, MCE, or AutoCartography until their planned milestone is reached.
