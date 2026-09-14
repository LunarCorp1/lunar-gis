# ADR-0007: Security and Supply-Chain Hardening

- Status: Accepted
- Date: 2026-09-14
- Deciders: ai-security-reviewer, dependency-license-auditor, architect, lunar-gis maintainers
- Related: AGENTS.md:4,5,8,10, docs/security/SECURITY_MODEL.md, docs/adr/ADR-0004-module-boundaries.md, pyproject.toml, .github/workflows/ci.yml, tests/unit/test_packaging.py

## Context

P0-T08 left the foundation with `pytest --cov 44%`, `ruff`, `mypy`, and `python -m build` gates, but no automated check for insecure Python patterns or accidental secret leakage. `docs/security/SECURITY_MODEL.md` already forbids hard-coded keys, arbitrary URLs, and binary exec, yet CI would not catch a `Bandit B602` subprocess call or a committed `.env` with `OPENROUTER_API_KEY`. A lightweight, reproducible security gate is needed before M1 tool-execution.

## Decision

Add a security/supply-chain gate as dev/CI-only tooling, no runtime change:

| Area | Decision | Evidence |
|------|----------|----------|
| **Bandit** | `bandit[toml]>=1.7` dev-only, scans `lunar_gis/` via `pyproject.toml: [tool.bandit] exclude_dirs = ["tests","build","dist"]` (understandable, no blanket `skips`). Single finding `B110 try_except_pass` in `lunar_gis/project/context.py:40` was fixed to `except Exception: crs_authid = None` (defensive QGIS invalid-CRS, not `pass`) → `bandit -r lunar_gis` now 0 issues | `pyproject.toml:17`, `bandit -c pyproject.toml -r lunar_gis -f screen` |
| **Gitleaks** | `gitleaks/gitleaks-action@v3.0.0` pinned to SHA `e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e` (Node24, not EOL v2; verified via `git ls-remote https://github.com/gitleaks/gitleaks-action refs/tags/v3.0.0` and `api.github.com/repos/gitleaks/gitleaks-action/tags`), with `fetch-depth: 0`, `GITHUB_TOKEN`, `permissions: contents: read`. No `pip` runtime dep, no credentials needed. Local: `gitleaks detect --source . --no-git --verbose` (worktree) vs CI history scan | `.github/workflows/ci.yml:48` |
| **Git hygiene** | `.gitignore` already protects `.env`, `.env.*` (`!.env.example` exception), `.opencode/node_modules/`, coverage artifacts (`.coverage` etc.). Verified `git check-ignore -v .env` ignored, `.env.example` not ignored, `git ls-files` shows no `egg-info`/`dist`/`build` | `.gitignore:14`, `git ls-files` |
| **Dependencies** | Runtime `dependencies` stays empty; `dev` adds `bandit[toml]` (Apache-2.0, not distributed, GPL-2.0-or-later compatible via `or-later` → GPL-3.0 upgrade path, dev-only). `gitleaks-action` is `Other` proprietary EULA (Gitleaks LLC) CI-only, not distributed. No vulnerability service added; GitHub `Dependabot` + existing `actions` pinning suffices for now | `pyproject.toml:15` `importlib.metadata.requires` |
| **CI separation** | `security-gate` job runs independently from `quality-gate` (`bandit` + `gitleaks` vs `ruff/mypy/pytest/build`), clearer failures, no QGIS/credential/network requirement | `.github/workflows/ci.yml` |
| **Actions SHA pinning** | `actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2` and `actions/setup-python@42375524e23c412d93fb67b49958b491fce71c38 # v5.4.0` pinned to immutable SHAs (verified via `git ls-remote` + GitHub API `api.github.com/repos/.../git/refs/tags/...`), `gitleaks-action` also SHA-pinned; human-readable `# vX.Y.Z` comments preserve maintainer readability. `permissions: contents: read` least-privilege on both jobs | `.github/workflows/ci.yml:13,35` |
| **Dependency reproducibility** | No lock file added for P0 foundation: 6 dev deps (`bandit[toml]`, `build`, `mypy`, `pytest`, `pytest-cov`, `ruff`) are lower-bounded `>=` without upper pin or `uv.lock`/`poetry.lock`; `pip install -e .[dev]` is single-source via `pyproject.toml`. Lightweight `>=` is sufficient for plugin foundation (no transitive compiled deps, QGIS bundles Python, no `pip-tools`/`Poetry`/`uv` complexity). Decision explicitly documented here rather than adding redundant lock/Dependabot automation at this stage (re-evaluate at M1 if `numpy`/`requests` added) | `pyproject.toml:15` |

Single source for `fail_under` remains `pyproject.toml`; security tools do not alter it.

## Alternatives considered

* **No Bandit / keep manual review only** — rejected: would miss `B110` and future `B602`/`B307` etc. silently.
* **Bandit `skips = ["B110"]` blanket** — rejected: would hide future genuine `try_except_pass` in `data` provider; fixed single site explicitly.
* **`detect-secrets` / `trufflehog` instead of Gitleaks** — rejected: Gitleaks is `AGENTS.md` preferred, maintained `gitleaks-action`, no extra Python dep.
* **`pip` `gitleaks` runtime dep** — rejected: no PyPI `gitleaks`; Go binary via Action is correct, not runtime.

## Consequences

* Local `bandit -c pyproject.toml -r lunar_gis` and `gitleaks detect` (if installed) reproduce CI; documented in `README.md: Quality gate`.
* No `lunar_gis/` code now triggers Bandit; future `data` provider must handle `B110` narrowly.
* Secrets must never be committed; `.env.example` is the only allowed example, all real `.env` ignored.
* Any gate change needs ADR per `docs/adr/README.md` lifecycle.

## Addendum 2026-09-14 — P0-T10 Hardening

* SHA pinning verified via `git ls-remote` and `api.github.com` (not invented): `checkout v4.2.2 → 11bd71901bbe5b1630ceea73d27597364c9af683`, `setup-python v5.4.0 → 42375524e23c412d93fb67b49958b491fce71c38`, `gitleaks-action v3/v3.0.0 → e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e`. Human-readable `# vX.Y.Z` comments retained.
* Dependency lock deliberately **not** added: existing `pyproject.toml: optional-dependencies.dev` `>=` lower bounds are sufficient for 6 pure-Python dev tools; no `pip-tools`/`Poetry`/`uv`/`Dependabot` introduced to avoid speculative infrastructure (see Decision row). Revisit if compiled or version-sensitive deps added in later milestones.
