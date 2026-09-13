# Architecture Decision Records

Use numbered ADRs for decisions that affect architecture, security, compatibility, licensing, or public contracts. ADRs are immutable once Accepted; amendments are recorded as new ADRs superseding prior ones.

## When to create an ADR

* Change to module boundaries, dependency direction, or public plugin API
* Choice of GIS / QGIS / Qt / Processing API
* Security model, secret handling, or provider abstraction
* Build, packaging, or Python compatibility decisions
* Licensing or dependency policy changes

## Lifecycle

* `Proposed` → `Accepted` → `Deprecated` | `Superseded by ADR-NNNN`
* Keep `Status` and `Date` (YYYY-MM-DD) current; link superseded ADRs.

## Template (new ADRs from ADR-0004 onward)

```markdown
# ADR-NNNN: Title

- Status: Proposed | Accepted | Deprecated | Superseded by ADR-NNNN
- Date: YYYY-MM-DD
- Deciders: @role / @person
- Related: ADR-0001, AGENTS.md:1-12, docs/architecture/OVERVIEW.md, docs/security/SECURITY_MODEL.md

## Context
What problem, constraints, and QGIS/phase context motivated the decision.

## Decision
What was decided, in present tense.

## Alternatives considered
What else was evaluated and why it was rejected.

## Consequences
What becomes easier/harder, including security, QGIS compatibility, licensing, and testing impacts.
```

Existing ADRs 0001–0003 predate this template and use `Decision/Rationale/Consequences`. They are grandfathered; amend via addendum rather than rewriting history. New ADRs must use the template above.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| ADR-0001 | QGIS Plugin Foundation | Accepted 2026-09-13 |
| ADR-0002 | AI Execution Boundary | Accepted 2026-09-13 |
| ADR-0003 | Local Data First | Accepted 2026-09-13 |
| ADR-0004 | Module Boundaries | Accepted 2026-09-13 |
| ADR-0005 | Build and Toolchain | Accepted 2026-09-13 |
