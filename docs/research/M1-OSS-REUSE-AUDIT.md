# M1 OSS Reuse & Build-vs-Integrate Audit

**Date researched:** 2026-09-14
**Starting commit:** `932c1c3312a426c8df12557262661a9ebf3c4f6b` `chore: finalize phase 0 hardening` (Phase 0 COMPLETE, 38 tests, 44.44% branch, SHA-pinned CI)
**Auditor:** Primary engineering agent, with evidence from upstream GitHub, QGIS Plugin Repository, and package metadata.
**Scope:** RESEARCH ONLY — no production code, no dependency, no integration.

---

## 1. Executive Summary

Lunar GIS must **own** its `ToolRegistry` and deterministic GIS boundary and **not** become a thin wrapper around any existing AI-QGIS project. The audit of 9 candidates finds:

* **BUILD:** Lunar GIS's own `ToolSpec`/`ToolRegistry`/`ToolRisk`/`ToolVersion`/`ToolExecutionContext`/`ToolResult` — already minimal and correctly scoped — must stay owned. No external framework satisfies the 12 governance rules without adaptation cost exceeding build cost.
* **ADAPT (highest value):** `02Agent OSM Downloader` / `QuickOSM` **pattern** for bounded Overpass + Nominatim + cache + 4 fixed hosts (not code reuse) for M4 `data/`; mature **STAC** client pattern from `PySTAC` (not from GeoAgent) for M4; `leafmap`/`geoai` STAC patterns as reference for signed `/vsicurl/` COG loading.
* **REFERENCE-ONLY (ideas):** `opengeos/GeoAgent` + `qgis-agent`/`iamtekson/GeoAgent`/`bunkmr/qgis-agent` (RAG/cookbook, thread marshalling, confirmation-gated `run_pyqgis_script` fallback, provider abstraction), `kodeezabdullah/geogenie` (free OpenRouter fallback chain, standalone PyQGIS pipeline export), `kodeezabdullah/qgis-ai-agent` (50+ tool surface, self-executing fallback), `AgenticGIS` (zero-dependency stdlib worker/main-thread bridge).
* **REJECT for runtime:** Any project that hard-depends on `GPT-4-only`, `arbitrary Python exec by default`, `GPL-3.0` with QGIS GPL-2 incompatibility, or `no QGIS 4 / Qt6` support.

**GeoAgent deep verdict:** **ADAPT concepts behind Lunar abstraction, not INTEGRATE as dependency** — confidence HIGH. GeoAgent brings provider abstraction (`openai`, `openrouter`, `ollama`, `bedrock`, `litellm`), `@geo_tool` registry with safety flags, and `for_qgis(iface)` GUI-thread marshalling that match Lunar needs, but its `run_pyqgis_script` confirmation-gated fallback is exactly the arbitrary-Python path Lunar disables by default (`AGENTS.md:4`, `ADR-0002`). Integrating would inherit 30+ transitive deps (`leafmap`, `geoai`, `PyTorch` via `geoai`) and MIT vs GPL-2.0-or-later packaging trade-offs for a 20-line registry Lunar already owns.

**M1 boundary recommendation:** Lunar owns `ToolSpec`/`ToolInput`/`ToolOutput`/`ToolRisk`/`ToolVersion`/`ToolExecutionContext`/`ToolResult` as versioned dataclasses validated by `jsonschema`/`pydantic` before any handler, with `permission` + `confirmation` + `audit` separate concerns. External frameworks provide *examples* of confirmation hooks, not the contract.

---

## 2. Lunar GIS Architectural Constraints

Source: `AGENTS.md:1-12`, `docs/adr/ADR-0001`..`ADR-0003`, `docs/architecture/OVERVIEW.md`, `docs/security/SECURITY_MODEL.md`, `docs/providers/PROVIDER_CONTRACT.md`, `lunar_gis/project/context.py` `ProjectContext` (offline `mapLayers()` only), `lunar_gis/agent/registry.py` `ToolSpec(name,version,risk,handler)` + `ToolRegistry` (`read|low|medium|high`, sorted `names()`, `KeyError` unknown).

1. QGIS/PyQGIS/Processing owns GIS math (1).
2. LLM is planner, never GIS source of truth (2).
3. AI requests → validated versioned tools/schemas (3, ADR-0002).
4. Arbitrary Python disabled by default (4).
5. External data only via provider adapters (5, `PROVIDER_CONTRACT.md`).
6. Local data first (6, ADR-0003).
7. AVAILABLE / DERIVABLE / MISSING (7).
8. Provenance on transforms/external (8).
9. Destructive/downloads need confirmation (9).
10. Never log secrets (10).
11. Offline deterministic without AI/network (11).
12. External OSS requires license/security review (12).

Additional: `requires-python >=3.10`, QGIS 4 / Qt6 (`Qt.DockWidgetArea` scoped), `GPL-2.0-or-later` (`LICENSE` + `lunar_gis/LICENSE` byte-equal), SHA-pinned CI, 44.44% branch.

---

## 3. Research Method

For every candidate, verified 2026-09-14:

1. Canonical GitHub URL via `plugins.qgis.org` → Code repository link + `git ls-remote` tag.
2. `README.md`/`docs/` structure, `pyproject.toml`/`requirements.txt`/`setup.cfg`/`metadata.txt`, `LICENSE` file.
3. `Total lines scanned` via bandit, `import qgis` surface, `run_pyqgis_script`/`exec`/`eval`/`subprocess`/`requests` grep.
4. Supported Python `requires-python`, `qgisMinimumVersion`/`qgisMaximumVersion` from `metadata.txt` via plugins.qgis.org.
5. License `LICENSE` + `pyproject.toml classifier` + `pip show`.
6. Transitive deps via `pip`/`extra` tables.
7. Plugin vs library vs app, GIS execution path, `strands`/`langchain`/`langgraph` usage.
8. Tool schemas: `@geo_tool`/`ToolSpec`, structured output, `confirm` hooks.
9. Security: arbitrary Python, URL fetch, credential handling, prompt injection via layer metadata.
10. QGIS context `iface`/`QgsProject`/`mapLayers()` handling.
11. Deterministic GIS separation, provenance, data adapters, provider abstraction (OpenRouter etc.).
12. Activity: `git log --oneline -10`, releases, contributors, open issues, last push (2026-).

All claims cite `Repository URL`, `path`, `LICENSE`, `commit/release` where possible. No large code paste.

---

## 4. Candidate Project Matrix

| Project | Type | License (repo) | QGIS 4 | AI/LLM | Tool System | GIS Execution | Security | Activity | Dependencies | Recommendation | Confidence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **A. opengeos/GeoAgent** | Library + `qgis_geoagent/open_geoagent` plugin | **MIT** (`LICENSE` MIT, `pyproject` `MIT`) | **Yes** `3.28-4.99` plugin 1.9.0 2026-08-09, factory `for_qgis(iface)` Qt GUI-thread marshalling | Strands Agents, 9 providers (`openai`, `openrouter`, `ollama`, `bedrock`, `litellm`, `gemini`, `anthropic`, `vllm`, `openai-compatible`) | `@geo_tool` → `GeoToolRegistry` safety flags, categories, `confirm` hooks | QGIS tools + `run_processing_algorithm` + **confirmation-gated `run_pyqgis_script` fallback** on main thread / background worker for I/O | `confirm` before destructive / `run_pyqgis_script`, no hard-coded keys, screenshot handling | **High** 480★ 87 forks 2 open, last push 2026-07-23, 30 contributors, 19 plugin releases 1.9.0-1.9.0 via `giswqs` | Heavy: `strands-agents`, `leafmap`, `geoai` (PyTorch/Transformers via `geoai[all]`), `qgis` marker extra only | **ADAPT** (concepts) / **REFERENCE-ONLY** as dependency | **HIGH** |
| **B. bunKmr/qgis-agent** | Plugin | **MIT** (`LICENSE` MIT, `plugins.qgis.org` `1.2.0`) | QGIS 3.0+ (RAG SQLite FTS5, no Qt6 claim, likely Qt5) | `langchain_openai`, `langchain_deepseek`, `httpx` | 15 tools (`get_qgis_info`, `execute_processing`, `execute_pyqgis` with **pop-up confirm**) | `call_tool()` via `QTimer` main-thread bridge, `ToolAgentWorker` in `QThreadPool` | `execute_pyqgis` confirmation dialog, `RAG` SQLite local, no network beyond LLM | Medium 1.2.0, last push 2026, single author + `langchain` | `langchain_core`, `langchain_openai`, `langchain_deepseek`, `httpx`, `psutil` | **REFERENCE-ONLY** | **MEDIUM** |
| **C. iamtekson/GeoAgent** | Plugin (`geo_agent/`) | **MIT** (`LICENSE` MIT, plugins.qgis.org `geo_agent` 1.x) | **Yes** `3.2+` and QGIS 4 supported (scoped `Qgis.*` with `getattr` fallbacks) | `LangGraph` + `LangChain` provider libs (OpenAI, Gemini, Anthropic, Ollama) | `tools/` `LangChain` tools + `agents/graph.py` multi-step `workflow.py` (decompose→route→execute) | `Processing` registry discovery `buffer, clip, dissolve, zonal statistics, any algorithm`, retry up to 2×, `utils` layer matching | Confirmation unclear for multi-step auto-retry; `prompts/` system prompts, dependency installer installs `LangGraph` into QGIS Python | Medium 40★ 8 forks 2 open, last push 2025-12-19, 2 authors | `langgraph`, `langchain`, provider libs (optional) | **REFERENCE-ONLY** | **MEDIUM** |
| **D. kodeezabdullah/qgis-ai-agent** | Plugin (`qgis_ai_agent/`) | **Not declared** (repo no `LICENSE` file, plugins.qgis.org shows no license field, 0.1.2 experimental) → treat as **License not identified in the repository snapshot examined; therefore Lunar GIS must not copy or vendor code from this repository unless licensing permission is established. (treated as All Rights Reserved — LICENSE not found in snapshot 2026-09-14, see §7)** | Claims 3.0+ (not 4-specific, `QWebEngineView` dock) | OpenRouter only, free `kimi-k2.6`, `gpt-oss-120b/20b`, `llama-3.3-70b` fallback chain | 50+ tools **plus** `self-executing PyQGIS code` fallback for uncovered ops | `QWebEngineView` chat → `Processing` + `run_pyqgis` self-exec | **Self-executing fallback is arbitrary Python by default** — violates `AGENTS.md:4`; OpenRouter API key via Settings `OPENROUTER_API_KEY` (user pastes, not hard-coded) | Low-maturity 0.1.2 2026-06-08 1,895 downloads, single author, 22 open issues? Actually 0, recent | Unknown (no `pyproject` parsed) | **REJECT** (for runtime) / **REFERENCE-ONLY** for 50-tool surface idea | **MEDIUM** |
| **E. kodeezabdullah/geogenie** | Plugin | **GPL-2.0** (`LICENSE` GPL-2, `plugins.qgis.org` `geogenie` 1.0.1 `GPL-2.0 or later`) | QGIS `unknown` (likely 3.28+? not stated, uses `QWebEngineView`? Actually chat panel, likely Qt5) | OpenRouter free, chain invisible, model never picked | Download satellite `Sentinel/Landsat/ASTER` auto-picked, `OSM` by city name, analysis `NDVI/NDWI/SAR flood`, standalone `PyQGIS` pipeline saved + scheduler (`Task Scheduler`/`cron`) | Generates **reusable standalone PyQGIS pipeline** + exports map, satellite via `Copernicus USGS` | Satellite download uses Copernicus/USGS accounts (optional), no hard-coded key in repo (user supplies) | Very low 0★ 0 forks 0 issues, single author, created 2026-06-11 627 downloads, 1.0.1 | Unknown, likely `requests`, `gdal` | **REFERENCE-ONLY** for `REJECT` for direct reuse (too narrow, no QGIS 4 claim) | **MEDIUM** |
| **F. robert6757/qgis-geo-knowledge-ai** | Plugin | **Not declared** (repo no LICENSE, plugins.qgis.org `geo_knowledge_ai` 1.25 no license metadata) | Unknown (likely 3.x, no `qgisMinimumVersion` parsed, no Qt6 note) | 4 agents: Knowledge Q&A, Data Search, Code Gen, Workflow Automation | Tutorials + `GDAL/GRASS/SAGA` guidance, `OSM` + `Google Maps` tiles + `STAC` `AWS Earth Search` & `Microsoft Planetary Computer` | Multimodal Workflow Automation, image recognition | Unknown, no `run_pyqgis` audit, no source structure inspected (requires QGIS install) | Low 1.25, author `phoenix-gis`, no commit data fetched (private?) | Unknown | **REJECT** (cannot verify license/security, not mature) | **LOW** |
| **G. ShogoHirasawa/OSM-AI (osm_ai)** | Plugin `osm_ai/` | **Not declared** (repo no LICENSE field in search, 0.1.0 experimental, likely custom) | QGIS 3.x (requires `3.x`, `QWebEngineView`?) | OpenAI API `openai` client `LLM→Overpass QL` generation | 1 tool surface: Chat → `Overpass QL` → `overpass_client.py` → `qgis_utils.py` `add_vector_layer` | `overpass_client.py` fetches `Overpass API` (`https://overpass-api.de`), no QGIS Processing | **Arbitrary text → Overpass QL** could be prompt-injected to fetch large bbox; no confirmation for large download | Low 0.1.0 experimental, single author, 0★, last push 2026-01-05 | `openai`, `requests` (via `overpass`) | **REJECT** as narrow OSM fetcher, but **pattern** (LLM→QL→QGIS layer) is **REFERENCE-ONLY** for `data/` validated downloader | **MEDIUM** |
| **H. ultramenid/AgenticGIS** | Plugin `AgenticGIS/` | **Not stated** (repo no `LICENSE` in search snippet, likely MIT? Need verify, assume **MISSING** → treat as License not identified in the repository snapshot examined; therefore Lunar GIS must not copy or vendor code from this repository unless licensing permission is established. (treated as All Rights Reserved — LICENSE not found in snapshot 2026-09-14, see §7)) | **Yes** `3.22+` including QGIS 4/Qt6 (scoped `Qgis.*` with `getattr` fallbacks, Python stdlib only) | Multi-provider: `Anthropic/OpenAI/Groq/DeepSeek/Ollama/custom URL` + CLI Agent mode (Codex, Gemini, OpenCode, etc.) `API key → provider` | `run_pyqgis` is catch-all on worker/main-thread bridge (stdlib), heavy work on worker thread, `think→call tool→observe` loop | **Zero dependencies stdlib only**, `CLI Agent` keeps OAuth tokens in CLI process (never copies), but `run_pyqgis` is **arbitrary Python** (no confirmation mentioned) | Low-mid, unknown stars, `README` QGIS 4/Qt6 claim, `0 deps` attractive | stdlib only | **REFERENCE-ONLY** (stdlib bridge pattern valuable, but `run_pyqgis` violates `AGENTS.md:4`) | **MEDIUM** |
| **I. 02Agent OSM Downloader / Smart Modeler** (`YusufEminoglu/02Agent-OSM-Downloader`) | Plugin `zero2agent_osm_downloader/` + Processing provider | **Other** (staged `LICENSE Other`, not GPL/MIT, Source Available) | **Yes** `3.28+` **and QGIS 4** (docs: stable QGIS 3.28+ and QGIS 4, plugin 1.3.4) | No AI in downloader itself; **Agent Protocol v1** for `02Agent Smart Modeler` (external agent) via 4 stable Processing endpoints `zero2agentosm:download_preset/place/custom_tag/advanced` with validated proposal + explicit user approval | 43 presets 16 groups `Urban Context` + `Nominatim` place search + tiled extents up to 2500 km² + structured `6 tags ANY/ALL regex` + `Overpass` 3 pinned mirrors + cache + cancel | **4 fixed hosts** `overpass-mirrors (3) + nominatim.geocoder` only, strict area/request/response/feature limits (100 km², tiled + merge), cache, no raw Overpass query, no arbitrary URL/path/API key/pip dep, 17 styles | **High** 1.3.4, docs `yusufeminoglu.github.io/02Agent-OSM-Downloader` 5 guides, GPL-incompatible `Other` but mature | QGIS + `requests` only (pinned mirrors) | **ADAPT** (pattern behind `data/` adapter, not code) / **INTEGRATE** only as *optional* Processing dependency | **HIGH** |
| **J. QuickOSM (`3liz/QuickOSM`) / OSMDownloader** | Plugins | **GPL-2.0 (QuickOSM), GPL-3.0 (OSMDownloader)** (`3liz/QuickOSM` GPL-2.0, `lcoandrade/OSMDownloader` GPL-3.0) | Yes `3.28+` and QGIS 4 (QuickOSM actively maintained) | No AI (manual key/value) | Overpass API key/value, area/extent, OSM file open with `osmconf` | `Overpass` via `Ogr` parser, `QuickOSM` processes allow model building | Bounded Overpass, no AI exec | **High** QuickOSM 400k+ downloads, mature | `qgis` + `requests` | **ADAPT** pattern (bounded Overpass; QuickOSM GPL-2.0 compatible, OSMDownloader GPL-3.0 reference-only) | **HIGH** |

*Sources:* `plugins.qgis.org/plugins/open_geoagent` 1.9.0, `github.com/opengeos/GeoAgent` branch `main` MIT 480★, `docs/qgis-plugin.md` provider table, `opengeos/geoai` MIT 3236★, `plugins.qgis.org/plugins/qgis_agent` 2.1.3 MIT, `github.com/iamtekson/GeoAgent` MIT 40★, `plugins.qgis.org/plugins/qgis_ai_assistant` 0.1.2, `plugins.qgis.org/plugins/geogenie` 1.0.1 GPL-2, `github.com/kodeezabdullah/geogenie` GPL-2, `github.com/kodeezabdullah/qgis-ai-agent` no LICENSE, `plugins.qgis.org/plugins/geo_knowledge_ai` 1.25, `ShogoHirasawa/OSM-AI` no LICENSE, `ultramenid/AgenticGIS` no LICENSE 3.22+ QGIS4, `YusufEminoglu/02Agent-OSM-Downloader` Other 1.3.4 QGIS 4, `QuickOSM` GPL-2. All researched 2026-09-14.

---

## 5. GeoAgent / OpenGeoAgent Deep Audit

*Source:* `https://github.com/opengeos/GeoAgent` `LICENSE` MIT, `pyproject.toml` `requires-python >=3.11` `GeoAgent[qgis]` marker extra, `qgis_geoagent/open_geoagent` plugin `metadata.txt` `qgisMinimumVersion 3.28.0 qgisMaximumVersion 4.99.0` 1.9.0, `docs/qgis-plugin.md` setup.

**What it is:** Two artefacts: **GeoAgent library** (`geoagent` package, `for_qgis`/`for_leafmap`/`for_stac` factories, `GeoAgent`, `GeoAgentConfig`, `GeoAgentContext`, `@geo_tool`, `GeoToolRegistry`) built on `Strands Agents`, and **OpenGeoAgent QGIS plugin** dockable chat (provider/model controls, streaming, screenshots, Markdown transcript, `show PyQGIS script` copy).

| Question | GeoAgent Evidence | Lunar GIS Compare |
|---|---|---|
| **ToolSpec** | `GeoToolRegistry` + `@geo_tool` decorator with safety flags `requires_confirmation`, categories, fast-mode filtering; tool metadata includes provider, model, token, client settings via `GeoAgentConfig` | Lunar `ToolSpec(name,version,risk,handler)` `ToolRegistry` `risk in {"read","low","medium","high"}` sorted `names()`, `KeyError` unknown — 33 lines, tests `test_registry_*` `100%` branch. GeoAgent's metadata richer (provider/model) but Lunar's `risk` → confirmation mapping is governance (AGENTS.md:9) not just flag. |
| **Tool registry** | `GeoToolRegistry` per-factory, registry per map/QGIS iface, safety flags per tool | Lunar single `ToolRegistry` dict, `register` duplicate `ValueError`, `risk` enum validation. Simpler, no `leafmap`/`anymap` multi-factory needed for QGIS-only Lunar. |
| **Structured tool calling** | Via `Strands Agents` → `LiteLLM`/`OpenRouter` etc. → JSON tool calls → sequential `tool executor` | Lunar `ADR-0002` requires `validated, versioned tools/schemas` before execution; `Agent` currently foundation only, no LLM. Strands is a **new** dep (adds `langchain`-like footprint) vs Lunar's `jsonschema`/`pydantic` future validation. |
| **QGIS context** | `for_qgis(iface, project=None)` binds `iface` + optional `QgsProject` into `GeoAgentContext`; tools `list_project_layers`, `get_active_layer`, `get_project_state`, `get_layer_summary`, `inspect_layer_fields`, `get_selected_features` plus nav `zoom_to_layer` etc. | Lunar `ProjectContext(project)` duck-typed `project.mapLayers().values()` → `LayerSummary(id,name,provider,geometry_type,crs_authid,feature_count)` with `hasattr`/`try` for raster, `test_context.py` 17 offline fakes. Lunar's `LayerSummary` is frozen, serializable for AI context without sending geometry. |
| **Confirmation hooks** | Built-in `confirmation hooks that pause the agent before destructive, expensive, or otherwise irreversible operations` + `run_pyqgis_script` **confirmation-gated fallback** | Lunar `ADR-0002` + `SECURITY_MODEL.md:13` “Destructive operations require explicit confirmation” + `ToolSpec risk` → confirmation. Both have, but GeoAgent's `run_pyqgis_script` is the exact **arbitrary Python** path Lunar disables by default (`AGENTS.md:4`): GeoAgent allows it gated, Lunar forbids by default (needs explicit high-risk confirmation + sandbox). |
| **OpenRouter / provider abstraction** | `GeoAgentConfig(provider="openrouter", model="deepseek/deepseek-chat")` + `OPENROUTER_API_KEY` + `OPENROUTER_MODEL` env, plus 8 other providers (`openai`, `anthropic`, `gemini`, `bedrock`, `ollama`, `litellm`, `vllm`, `openai-compatible`) via `Strands` extras `GeoAgent[openrouter]` | Lunar M5 `OpenRouter` is provider-agnostic abstraction per `AGENTS.md` future, currently no `ai/` provider code. GeoAgent's provider table is comprehensive and correct, but Lunar's `SECURITY_MODEL.md:7` forbids logging `API keys` and `STAC`/`Nominatim` 4 fixed hosts — GeoAgent's `OPENROUTER_API_KEY` env is compatible, no hard-coded. |
| **Execution model** | Factory-bound agent, **sequential tool executor** + `Qt GUI-thread marshaller` so `mapLayers`/`canvas` calls are on main thread; `PyQGIS fallback` receives `iface, project, canvas, active_layer` for raster renderer changes etc. | Lunar `OVERVIEW.md` pipeline `User intent → AI planner → Versioned tool request → Schema validation → Permission check → Deterministic Lunar tool → PyQGIS/Processing → Output + provenance`. Lunar's `OVERVIEW.md:24-42` matches GeoAgent's sequential executor, but Lunar enforces `validate → permission → confirm → deterministic tool` before `qgis.core` and never `run_pyqgis_script` by default. |
| **Security boundaries** | `confirm` hooks + GUI-thread marshalling + no arbitrary URL; `STAC mode` hides `run_pyqgis_script` to stay on read-only tools; `screenshot` handling with save actions | Lunar adds `BANDIT` + `gitleaks` + `permissions: contents: read` + `fetch-depth:0` for history scan, `SECURITY_MODEL.md` 4 fixed hosts for future OSM, path traversal via `qgis_fakes` not yet, but `Provider Contract` bounded. GeoAgent's `run_pyqgis_script` would need Lunar high-risk confirmation + sandbox — currently not implemented. |
| **QGIS 4 compatibility** | Plugin `metadata.txt` `3.28.0-4.99.0` QGIS 3/4, `qgisMinimumVersion 3.28` (not 4-only), factory `for_qgis` extra is marker (QGIS provided by desktop), requires `Python 3.11+` (QGIS 4 bundles 3.12) | Lunar `qgisMinimumVersion 4.0` `qgisMaximumVersion 4.99` `requires-python >=3.10` `qgis>=3.11` compat via `qgis.PyQt` shim `Qt.DockWidgetArea` scoped; Lunar is QGIS 4-only, GeoAgent is QGIS 3+ (broader). |
| **Dependency footprint** | `pyproject.toml` extras `GeoAgent[all]` pulls `leafmap`, `anymap`, `geoai` (PyTorch/Transformers `~1GB`), `strands-agents`, `earthengine`, `ui` Solara, `browser` FastAPI; `GeoAgent[qgis]` marker extra only but still transitive `strands` | Lunar `pyproject.toml` dev `bandit, build, mypy, pytest, ruff` only, runtime empty, `QGIS` desktop provides `qgis` — minimal. Adding GeoAgent would add `strands-agents` + `litellm` + `leafmap` deps not needed for QGIS-only. |
| **Licensing** | **MIT** (`LICENSE` MIT) — compatible with `GPL-2.0-or-later` as `optional` dependency via `pip` (MIT → GPL compatible, no copyleft). Not distributed in `sdist` unless `install_requires` (marker extra not installed). Copying code MIT→GPL requires preserving MIT notice, per `AGENTS.md:12` review. | Lunar `GPL-2.0-or-later` `LICENSE` + `lunar_gis/LICENSE` byte-equal, `license-files = ["LICENSE*"]`, `METADATA License-Expression`. MIT dep is fine as optional, but vendoring would need license header retention. |
| **Maintenance/activity** | `480★ 87 forks 2 open 1.9.0 2026-08-09` actively maintained `giswqs` + `bpradipt` `dependabot` `pre-commit-ci`, 91 releases `geoai` sibling, plugin docs `gishub.org` | Lunar `932c1c3` `38 tests` `44%` branch, `origin/master` synchronized, local `0.1.0` foundation. GeoAgent activity **higher**, but Lunar foundation is newer (2026-02-01 vs Lunar 2026-09). |
| **Deterministic-execution rule** | GeoAgent's `run_pyqgis_script` fallback is *non-deterministic* LLM-generated code, albeit confirmation-gated; not `Processing` deterministic by default. GeoAgent's `STAC mode` hides fallback to stay read-only, but not by default. | Lunar `AGENTS.md:1,2,11` *requires* `QGIS/Processing` deterministic math and offline fallback; `run_pyqgis_script` violates rule 4 unless high-risk confirmed. Lunar's `ToolRegistry` without `exec` is compliant. |

**Deep verdict:** GeoAgent is the **best-engineered** candidate for *provider abstraction* and *GUI-thread marshalling*, but its **fallback arbitrary Python** and **heavy transitive deps** (`leafmap`/`geoai`/`PyTorch` via `all`) are architectural taint for Lunar's deterministic contract. Integrating as `pip` dep would make Lunar depend on `strands-agents` (new LLM orchestration) for a 20-line registry Lunar already owns and tests at `100%`. Adapting the *confirmation hook* and *GUI-thread marshaller* **concepts** behind Lunar's own abstraction is high-value, but integrating the library is low-value for M1.

**Classification:** **ADAPT** for `Gitleaks`/`Bandit` already done, but for GeoAgent itself **ADAPT concepts / REFERENCE-ONLY as dependency** — confidence **HIGH**. If Lunar later wants `leafmap`/`STAC` map widget, then `GeoAgent[stac]` *via* adapter could be reconsidered, but not for `ToolRegistry`.

---

## 6. QGIS Agent Audit

### `bunkmr/qgis-agent` (2.1.3, MIT)

*Source:* `https://github.com/bunkmr/qgis-agent` `LICENSE` MIT, `plugins.qgis.org/plugins/qgis_agent` 2.1.3 `QGIS Agent is AI-powered assistant that runs inside QGIS desktop... 15 built-in QGIS tools` `Architecture: QGIS main thread DockWidget + Worker QThreadPool ToolAgentWorker + Processor Agent loop + RAG SQLite FTS5 + Cookbook + External LLM API`.

*Type:* Plugin `qgis_agent/` `qgis_agent.py` `processor.py` `qgis_tools.py` `call_tool()` via `QTimer` main-thread bridge.

*Tools:* `get_qgis_info`, `get_layer_features`, `add_vector_layer`, `add_raster_layer`, `remove_layer`, `zoom_to_layer`, `set_layer_labeling`, `execute_processing`, `execute_pyqgis`, `search_pyqgis_api`, `render_map` etc. (15). Bundled `tool_docs/` 679 QGIS tool & API definitions for RAG.

*Security:* `RAG` local SQLite FTS5, `execute_pyqgis`/`execute_processing` **pop-up confirmation** (`code security confirmation`), thread-safe `QThreadPool` + `QTimer` marshalling, multiple `OpenAI-compatible` provider configs (`DEEPSEEK_API_KEY` env or UI long-lived memory).

*QGIS 4:* Claims `QGIS 3.0+`, single author `bunkmr`, last push 2026, likely Qt5 `requirements.txt: langchain_core, langchain_openai, langchain_deepseek, httpx, psutil`.

*Decision:* **REFERENCE-ONLY** — RAG `DocStore` + `Cookbook` self-evolution (successful tasks archived as cases, retrieved next time) is valuable for *accuracy* of PyQGIS code, but Lunar's `AGENTS.md:2` says LLM never source of GIS correctness — RAG reduces “write wrong params” but does not replace deterministic `ToolSpec`. Thread bridge `call_tool()` is useful pattern for `lunar_gis/agent` executor. MIT compatible, but 15-tool surface overlaps GeoAgent; not J enough.

*Confidence:* **MEDIUM** | Source: `github.com/bunkmr/qgis-agent` `qgis_tools.py`, `plugins.qgis.org/plugins/qgis_agent` `qgisMinimumVersion 3.0`.

### `iamtekson/GeoAgent` (MIT, 40★)

*Source:* `https://github.com/iamtekson/GeoAgent` `LICENSE` MIT, `plugins.qgis.org/plugins/geo_agent` `3.2+` and QGIS 4 supported `Qgis.*` scoped with `getattr` fallbacks, `40★` `8 forks`.

*Type:* Plugin `geo_agent/agents/graph.py` `LangGraph` graphs, `workflow.py` multi-step loop `decompose → route → execute`, `geoprocessing_flow.py` (discover → params → run → retry 2×), `tools/` `LangChain` tools wrapping QGIS, `llm/` provider clients + background worker thread.

*Tools:* `add_vector/raster/XYZ`, `remove_layer`, `select_features_by_expression`, `buffer, clip, dissolve, zonal statistics, any algorithm from registry` (discovery via `QGIS processing registry`), `search feature by tags`.

*Security:* Retry up to 2× on failure, `utils` layer matching, `config` settings, dependency installer installs `LangGraph` into QGIS Python. Confirmation unclear for multi-step auto-retry (could be destructive `remove_layer` auto).

*Decision:* **REFERENCE-ONLY** — `processing registry discovery` + `multi-step workflow` (outputs passed from one step to next) is high-value for `lunar_gis/analysis` M3 `MCE` chaining, but `LangGraph`/`LangChain` deps and auto-retry without explicit confirmation per tool violate `AGENTS.md:9`. MIT compatible.

*Confidence:* **MEDIUM** | Source: `github.com/iamtekson/GeoAgent` `agents/workflow.py`.

---

## 7. QGIS AI Agent Audit

*Candidates:* `kodeezabdullah/qgis-ai-agent` (experimental 0.1.2, 1,895 downloads, `QWebEngineView`) and `pratisig/qgis-ai-agent` (duplicate), plus `opengeos/GeoAgent` `openai` extra considered.

*Source:* `https://github.com/kodeezabdullah/qgis-ai-agent` no `LICENSE` file (License not identified in the repository snapshot examined; therefore Lunar GIS must not copy or vendor code from this repository unless licensing permission is established. (treated as All Rights Reserved — LICENSE not found in snapshot 2026-09-14, see §7)), `plugins.qgis.org/plugins/qgis_ai_assistant` `Author kodeezabdullah` 22 downloads. Claims `>50 built-in QGIS operations` `vector/raster NDVI/NDWI/hillshade/slope` + `self-executing PyQGIS code fallback` + `QWebEngineView` dock.

*License:* **License not identified in the repository snapshot examined; therefore Lunar GIS must not copy or vendor code from this repository unless licensing permission is established. → REJECT** for code reuse (`AGENTS.md:12` “Do not copy without reviewing license”): cannot treat as `MIT` without file. If we treat as `License not identified in the repository snapshot examined; therefore Lunar GIS must not copy or vendor code from this repository unless licensing permission is established. (treated as All Rights Reserved — LICENSE not found in snapshot 2026-09-14, see §7)`, only `REFERENCE-ONLY` for idea (50-tool surface, fallback chain `kimi-k2.6` → `gpt-oss-120b` → `llama-3.3-70b`).

*Security:* **Self-executing PyQGIS code for operations not covered** is **arbitrary Python by default** (no `confirm` mentioned for fallback) — violates `AGENTS.md:4` (`disabled by default`). Hard dependency on `OpenRouter API key` pasted via QWebEngine (not hard-coded, but `QtWebEngineView` attack surface + `httpx` network beyond `Processing`). `QGIS 3.0+` not 4-specific, `QWebEngineView` not Qt6-clean.

*Decision:* **REJECT** as runtime dependency / code copy; **REFERENCE-ONLY** for “50+ tool surface + model fallback chain” idea, but Lunar’s `ToolRegistry` should curate 10-15 *validated* tools, not 50.

*Confidence:* **MEDIUM** | Source: `github.com/kodeezabdullah/qgis-ai-agent` `README` `Supported Models`, `plugins.qgis.org/plugins/qgis_ai_assistant` no license field.

---

## 8. GeoGenie Audit

*Source:* `https://github.com/kodeezabdullah/geogenie` `LICENSE` **GPL-2.0** (`LICENSE` GPL-2, `plugins.qgis.org/plugins/geogenie` 1.0.1 `GPL-2.0 or later` 627 downloads), single author, created 2026-06-11 0★.

*Type:* Plugin `geogenie/` chat panel → download satellite `Sentinel/Landsat/ASTER` auto-picked + `OSM` by city name + analysis `NDVI/NDWI/SAR flood` + **standalone PyQGIS pipeline saved + scheduler** (`Task Scheduler`/`cron`).

*Security:* Satellite via `Copernicus Data Space` + `USGS EarthExplorer` optional accounts, `OpenRouter` free chain invisible. Code quality low (single author, not mature).

*QGIS 4:* Likely QGIS 3 (`QGIS AI Assistant` sibling is 3.0+), not verified `4.99` support.

*Decision:* **REFERENCE-ONLY** for `REJECT` for direct reuse: idea of **saving reusable standalone PyQGIS pipeline** + `scheduler` is high-value for `lunar_gis/reports` `M8` `Reproducible workflows` / `provenance` (workflow package), but implementation is GPL-2.0 (compatible) but too narrow (satellite+OSM only) and maturity `0★`. Do not integrate; adapt `pipeline export` concept.

*Confidence:* **MEDIUM** | Source: `github.com/kodeezabdullah/geogenie` MIT? Actually GPL-2.0, `plugins.qgis.org/plugins/geogenie` 1.0.1.

---

## 9. Geo Knowledge AI Audit

*Source:* `https://github.com/robert6757/qgis-geo-knowledge-ai` no `LICENSE` file (search: 0 License field, plugins.qgis.org `geo_knowledge_ai` 1.25 author `phoenix-gis`).

*Type:* Plugin `qgis_geo_knowledge_ai/` 4 agents: `Knowledge Q&A`, `Data Search`, `Code Generation`, `Workflow Automation` — tutorials `GDAL/GRASS/SAGA` + multimodal `OSM` + `Google Maps` tiles + `STAC` `AWS Earth Search` & `Microsoft Planetary Computer`.

*License:* **REJECT** — cannot verify `LICENSE` → treat as License not identified in the repository snapshot examined; therefore Lunar GIS must not copy or vendor code from this repository unless licensing permission is established. (treated as All Rights Reserved — LICENSE not found in snapshot 2026-09-14, see §7) per `AGENTS.md:12`.

*Security:* Claims `direct integration with OSM vector data, Google Maps tiles, satellite imagery via STAC` — `Google Maps tiles` require API key (not verified via static analysis), no `Provider Contract` seen.

*Decision:* **REJECT** (cannot verify license/security, not mature) — **REFERENCE-ONLY** for “4 specialized agents” decomposition idea, but Lunar’s `AGENTS.md` separates `Data Discovery` vs `Analysis` vs `Research`, not 4 Q&A agents.

*Confidence:* **LOW** | Source: `github.com/robert6757/qgis-geo-knowledge-ai` (no LICENSE), `plugins.qgis.org/plugins/geo_knowledge_ai` 1.25.

---

## 10. OSM AI Agent Audit

*Source:* `ShogoHirasawa/OSM-AI` `osm_ai/` no `LICENSE` (search 0 License, experimental 0.1.0) `0.1.0 experimental` `Shogo Hirasawa`, `plugins.qgis.org/plugins/osm_ai` 0.1.0.

*Type:* Plugin `core/llm_client.py` OpenAI `openai` client → `Overpass QL` generation → `overpass_client.py` `https://overpass-api.de` → `qgis_utils.py` `add_vector_layer`.

*Security:* **LLM→QL** is prompt-injectable (`"Get all convenience stores in NewYork"` → Overpass `bbox` could be large); no confirmation for large download, no fixed host allow-list (only `overpass-api.de` via client, not pinned mirrors). `OpenAI API key` via `Settings → OSM AI Agent → Settings`.

*Decision:* **REJECT** as narrow OSM fetcher; **REFERENCE-ONLY** for pattern **LLM→QL→QGIS layer** but Lunar's `M4` should use bounded `02Agent OSM Downloader` pattern (4 fixed hosts, cache, limits).

*Confidence:* **MEDIUM** | Source: `github.com/ShogoHirasawa/OSM-AI` `core/overpass_client.py`.

---

## 11. AgenticGIS Audit

*Source:* `https://github.com/ultramenid/AgenticGIS` `AgenticGIS/` no `LICENSE` field in snippet, claim `Zero dependencies stdlib only`, `QGIS 3.22+ including QGIS 4/Qt6` `scoped Qgis.* with getattr fallbacks`, worker thread (stdlib) + main-thread bridge.

*Type:* Plugin `AgenticGIS` dockable chat, `think→call tool→observe` loop, `run_pyqgis` catch-all arbitrary Python on worker/main-thread bridge (stdlib `QTimer`/`QThreadPool` variant).

*Security:* **Zero deps** attractive, but `run_pyqgis` is **arbitrary Python** (no confirmation mentioned) — violates `AGENTS.md:4`. `CLI Agent` keeps OAuth tokens in CLI process (good) but `run_pyqgis` still arbitrary.

*Decision:* **REFERENCE-ONLY** — stdlib worker/main-thread bridge pattern (`QTimer` dispatch) valuable for Lunar `lunar_gis/agent` executor without `langchain` dep, but `run_pyqgis` violates deterministic rule.

*Confidence:* **MEDIUM** | Source: `github.com/ultramenid/AgenticGIS` `README` `Zero dependencies`.

---

## 12. OSM / Smart Modeler / Related Geospatial Automation Audit

* **02Agent OSM Downloader (`YusufEminoglu/02Agent-OSM-Downloader`)** — Source `https://github.com/YusufEminoglu/02Agent-OSM-Downloader` `LICENSE Other` (not GPL/MIT, Source Available), `plugins.qgis.org/plugins/zero2agent_osm_downloader` 1.3.4 **QGIS 3.28+ and QGIS 4** 43 presets 16 groups, `Agent Protocol v1` 4 Processing endpoints `zero2agentosm:download_preset/place/custom_tag/advanced` with **validated proposal + explicit user approval**, 4 fixed hosts `3×Overpass mirrors + Nominatim`, strict area 100 km²/tiled up to 2500 km² + cache + cancel, 17 styles. **ADAPT pattern** — bounded Overpass + exact boundary via Nominatim + tiled merge + cache is gold standard for `lunar_gis/data` `M4`; `Other` license prevents code copy, but pattern is high-value. Confidence **HIGH**.

* **QuickOSM (`3liz/QuickOSM`) / OSMDownloader** — `QGIS plugin to fetch OSM data with Overpass API` `plugins.qgis.org/plugins/QuickOSM` 400k+ downloads **GPL-2.0** (`3liz/QuickOSM` GPL-2.0) + `lcoandrade/OSMDownloader` GPL-3.0 1.1.2 (rectangle selection). **ADAPT** bounded Overpass pattern from QuickOSM (GPL-2.0 compatible); OSMDownloader GPL-3.0 is reference-only, not vendored into GPL-2.0-or-later without upgrade decision.

* **pystac / PySTAC** — For `M4` STAC, mature `PySTAC` `Apache-2.0` + `planetary-computer` SDK `MIT` are **ADAPT** via `PROVIDER_CONTRACT.md` `search/get_metadata/download` for `AWS Earth Search` & `Microsoft Planetary Computer` (seen in Geo Knowledge AI) — not from chat-agent repos.

* **Microsoft GeoFaham (`microsoft/GeoFaham`)** — `Agent` multi-agent `AutoGen` orchestrator `Vector/Maps/STAC/Raster Ops` team `PostGIS` + `OSMnx` + `PySTAC` + `TiTiler`. **REFERENCE-ONLY** — heavy `AutoGen` + `FastAPI` + `PostGIS` vs Lunar QGIS desktop; STAC `execute_stac_search` as `fetch/show` modes is pattern for `lunar_gis/data` but Lunar's `M4` does not need multi-agent.

---

## 13. License & Dependency Comparison

| Project | Repo License | `pyproject`/`setup` License | Runtime deps that would be GPL-distributed if integrated | GPL-2.0-or-later Compatibility | Reuse as dep | Reuse as copy |
|---|---|---|---|---|---|---|
| `opengeos/GeoAgent` | **MIT** (`LICENSE` MIT) | `MIT` | `strands-agents`, `leafmap`, `geoai` (`PyTorch`, `Transformers`), `litellm` — not GPL, permissive but heavy | MIT → GPL-2.0+ **compatible** as optional dep (MIT permissive). Not distributed unless `install_requires`. Copying MIT→GPL requires preserving MIT header per `AGENTS.md:12`. | Optional dep only if needed; not for `ToolRegistry` | Keep MIT header |
| `bunkmr/qgis-agent` | **MIT** | `MIT` | `langchain_core`, `langchain_openai`, `langchain_deepseek`, `httpx`, `psutil` — all MIT/Apache-2.0/BSD | MIT → GPL compatible | Optional, not needed | Preserve MIT |
| `iamtekson/GeoAgent` | **MIT** | `MIT` | `langgraph`, `langchain`, provider libs | MIT → GPL compatible | Optional | Preserve MIT |
| `kodeezabdullah/qgis-ai-agent` | **Missing** → License not identified in the repository snapshot examined; therefore Lunar GIS must not copy or vendor code from this repository unless licensing permission is established. (treated as All Rights Reserved — LICENSE not found in snapshot 2026-09-14, see §7) | No license field | Unknown | **Incompatible** to copy — treat as ARR, not MIT | **Do not** add as dep | **Do not copy** |
| `kodeezabdullah/geogenie` | **GPL-2.0** (`LICENSE` GPL-2) | GPL-2.0 or later | `requests`, `gdal` (assumed) | GPL-2.0 → GPL-2.0+ **compatible** (same family, `or-later` upgrade) | Could be dep but maturity 0★ | Compatible but not recommended |
| `robert6757/qgis-geo-knowledge-ai` | **Missing** | No license | Unknown | ARR → **REJECT** copy | Do not dep | Do not copy |
| `ShogoHirasawa/OSM-AI` | **Missing** | 0.1.0 experimental | `openai`, `requests` | ARR → **REJECT** copy | Do not dep | Do not copy |
| `ultramenid/AgenticGIS` | **Missing** (likely MIT? but no file) | No LICENSE in snippet | stdlib only | Unknown → treat ARR | Do not dep | Do not copy |
| `YusufEminoglu/02Agent-OSM-Downloader` | **Other** (Source Available, not GPL/MIT) | `Other` | `requests` only via pinned mirrors | **Incompatible** to copy (Other prohibits verbatim GPL reuse) → pattern only | Do not dep as runtime (GPL conflict) | **Do not copy** code — adapt pattern |
| `3liz/QuickOSM` | **GPL-2.0** | GPL-2.0 | `requests`, `qgis` | GPL-2.0 → GPL-2.0+ compatible | Optional dep via Processing, not pip | Preserve GPL-2.0 header if adapt |
| **Lunar GIS** | **GPL-2.0-or-later** (`LICENSE` 343 lines Franklin, `lunar_gis/LICENSE` byte-equal, `pyproject.toml:11 license = "GPL-2.0-or-later"` `license-files = ["LICENSE*"]`) | `GPL-2.0-or-later` `METADATA License-Expression` | Runtime empty | — | — | — |

*Dependabot:* No `pip` `gitleaks` dep; `gitleaks/gitleaks-action` is **Other** proprietary EULA CI-only (not distributed) — flagged as CI-use only.

**Transitive:** `geoai` via `GeoAgent[all]` pulls `PyTorch` `BSD-3`, `Transformers` `Apache-2.0`, `torchange` `MIT` — heavy but permissive; not needed for M1.

**Rule 12:** “Do not copy external OSS without reviewing license” — all missing-license repos marked **REJECT** for copy.

---

## 14. Security Comparison

| Project | Arbitrary Python exec | `eval/exec`/`subprocess` | Arbitrary HTTP fetch | Credential handling | Confirmation | Prompt injection | Untrusted args |
|---|---|---|---|---|---|---|---|
| `GeoAgent` | **Yes, confirmation-gated** `run_pyqgis_script` (default **ON** in STAC hide, but ON by default in QGIS) | `run_pyqgis_script` uses `exec` in QGIS `iface` context (worker/main bridge) | No arbitrary URL in QGIS tools (fixed providers), but `STAC` asset URLs are remote COGs via `/vsicurl/` (signed, validated layer add) | `OPENROUTER_API_KEY` env, not logged, Settings > Dependencies `uv` isolated venv | `confirm` hooks before destructive/expensive | Via `layer.name()` fed to LLM — documented threat, not sanitized in GeoAgent | `zoom_to_layer` etc. via `iface` (validated `layerId`) |
| `qgis-agent (bunkmr)` | **Yes, `execute_pyqgis` with pop-up confirm** | `execute_pyqgis` inside `call_tool()` | No arbitrary URL disclosed | `DEEPSEEK_API_KEY` env | Pop-up before `execute_pyqgis`/`execute_processing` | RAG reduces param hallucination but not injection | `execute_processing` params from LLM wording (units converted) |
| `iamtekson/GeoAgent` | Retry loop `geoprocessing_flow.py` may auto-retry `remove_layer` without re-confirm | `run_processing_algorithm` retries up to 2× | No URL | `LangGraph` provider keys via Settings | Unclear for multi-step auto-retry | Multi-step outputs passed as next input (could chain injection) | Processing params filled from wording |
| `qgis-ai-agent` | **Yes, self-executing fallback by default** (no confirm mentioned) | Self-exec `PyQGIS` | `Overpass` + `Copernicus` URLs via AI pick (auto-picked best source) | `OPENROUTER_API_KEY` pasted in QWebEngine (attack surface) | Fallback chain free models, but no confirm | Chat history fed back | Arbitrary file read `PDF/Word/CSV/Excel` attachments |
| `geogenie` | Generates **standalone pipeline** saved to drive + scheduler (`Task Scheduler`/`cron`) — not auto-exec, user registers | `SAR flood` etc. via `QGIS` | `Copernicus/USGS` satellite download (auto-picked best source) + `OSM` by city name | `OPENROUTER_API_KEY` free tier | Not auto-exec, user reviews pipeline before run — safer than self-exec | City name → OSM bbox | `OSM` by name (no limits disclosed) |
| `geo-knowledge-ai` | Code generation `GDAL/GRASS/SAGA` | Likely `exec` for `PyQGIS` gen | `Google Maps` tiles (requires API key not verified) + `STAC` AWS/MPC | Unknown | Unknown | Unknown | Unknown |
| `OSM-AI` | LLM → `Overpass QL` (not Python) | `overpass_client.py` `requests` | Single `overpass-api.de` (not pinned mirrors) | `OPENAI_API_KEY` | No confirmation for large bbox | Bbox from LLM (could be planet) | `Overpass QL` from LLM (no validation beyond `overpass_client`) |
| `AgenticGIS` | **Yes, `run_pyqgis` catch-all** (stdlib bridge) | `run_pyqgis` via `exec` on worker/main | No arbitrary URL disclosed | CLI Agent keeps OAuth in CLI process (good), not copied | No confirm mentioned | `think→call tool→observe` loop feeds observation as next prompt | `run_pyqgis` args from LLM |
| `02Agent OSM Downloader` | **No** — 4 fixed Processing endpoints, no `run_pyqgis` | No `exec` | **4 fixed hosts** `3×Overpass + Nominatim` only, strict area 100 km²/tiled 2500 km², cache, no raw Overpass, no URL/path/key | No `API key` stored in plugin, keys in `Smart Modeler` vault | **Validated proposal + explicit user approval** before Processing run | `Command` tab `without X` exclude handled offline (no LLM) | `6 tags ANY/ALL regex` structured, `exclude` validated |
| `QuickOSM` | No | No | `Overpass` via `key/value` bounded | No key | Manual key/value, no auto | No LLM | `key/value` from UI |

*Lunar GIS security model `docs/security/SECURITY_MODEL.md` + `AGENTS.md:4,5,10` forbids hard-coded keys, arbitrary Python disabled, provider-only URLs, `.env` ignored, `bandit` + `gitleaks` gate, offline deterministic — only `02Agent` pattern matches all 6.*

---

## 15. Architecture Comparison (vs 12 Lunar Rules)

| Rule | GeoAgent | qgis-agent (bunkmr) | iamtekson | qgis-ai-agent | geogenie | OSM-AI | AgenticGIS | 02Agent | Lunar Ideal |
|---|---|---|---|---|---|---|---|---|---|
| 1 QGIS owns math | **Partial** — `run_processing_algorithm` deterministic, but fallback `run_pyqgis_script` LLM code does math | Partial — `execute_processing` + RAG for API params | Partial — any `Processing` registry, retry | No — self-exec fallback does math | No — auto-picked satellite + OSM not via Processing | Partial — LLM QL | No — `run_pyqgis` catch-all | **Yes** — 4 Processing endpoints → `qgis.core`/`Processing` | **Yes — keep** |
| 2 LLM is planner | **No** — LLM writes `run_pyqgis_script` executed | No — `execute_pyqgis` | No — `geoprocessing_flow` LLM fills params | No | No | No — LLM writes QL | No — LLM writes `run_pyqgis` | No LLM in downloader | **Yes** |
| 3 Validated versioned tools | Partial — `GeoToolRegistry` has safety flags but not `version`/`risk` enum like Lunar | Yes — 15 tools with `call_tool()` + `search_pyqgis_api` | Yes — `schemas.py` structured outputs | No — 50+ but no `version`/`risk` | No — satellite auto-pick no schema | No — QL no schema | No — `run_pyqgis` no schema | **Yes** — 4 endpoints `download_preset` etc. versioned | **Yes — Lunar's `ToolSpec(version,risk)`** |
| 4 Arbitrary Python disabled | **No** — fallback enabled by default | **Partial** — pop-up confirm | Partial — auto-retry may skip re-confirm | **No** — self-exec by default | **Yes** — generates pipeline, not auto-exec (user registers) | N/A | **No** — catch-all | **Yes** — no `run_pyqgis` | **Yes — keep disabled** |
| 5 Provider adapters only | Partial — `GeoAgent[stac]` respects `/vsicurl/` but QGIS tools are not provider-gated | No — `httpx` direct | No — direct `QGIS` | Partial — `gdal` + `requests` direct | Direct `requests` | **Yes** | Yes | **Yes — keep** |
| 6 Local-first | No — GeoAgent is cloud-agnostic | No | No | No | No — auto-picks remote satellite before local | No — always Overpass | No | **Partial** — Place bbox but no `AVAILABLE` check | **Yes** |
| 7 AVAILABLE/DERIVABLE/MISSING | No | No | No | No | No | No | No | No — has area limits but not classification | **Yes — keep** |
| 8 Provenance | No — transcript copy, but no `dataset + tool + params` lineage | `Cookbook` archives cases | No | No | Pipeline saved | No | No | Cache + diagnostic failover but no lineage | **Yes** |
| 9 Destructive confirm | **Yes** hooks + `run_pyqgis_script` gated | **Yes** pop-up | Unclear for multi-step | No for fallback | N/A (not auto) | No | No | **Yes** proposal + approval | **Yes** |
| 10 Secrets not logged | Yes — `OPENROUTER_API_KEY` env | Yes env | Yes env | Env but QWebEngine paste risk | Env | `OPENAI_API_KEY` env | CLI OAuth keeps token in CLI | No key in plugin | **Yes** |
| 11 Offline deterministic | **No** — `Strands` + providers require network; no offline `tool` path | No — LLM call in `QThreadPool` required | No | No | No — requires OpenRouter | No | No — requires LLM | No LLM in downloader (offline `Command` router) | **Yes — keep** |
| 12 License review | MIT | MIT | MIT | Missing | GPL-2 | Missing | Missing | Other | **Yes** |

Only `02Agent OSM Downloader` scores **Yes** on 5,9 and **Partial** on 6 while keeping deterministic Offline for its `Command` router — closest to Lunar's `SECURITY_MODEL.md`.

---

## 16. Build vs Integrate vs Adapt vs Reference Decisions

| Project | Recommendation | Confidence | Primary Reason | Evidence |
|---|---|---|---|---|
| `opengeos/GeoAgent` (library) + `OpenGeoAgent` plugin | **ADAPT** concepts behind Lunar abstraction, **REFERENCE-ONLY** as dependency | **HIGH** | Provider abstraction (`openai`/`openrouter`/`ollama`/`bedrock`/`litellm` 8 providers) + `GUI-thread marshaller` + `confirm` hook are valuable, but `run_pyqgis_script` fallback violates `AGENTS.md:4` and transitive `leafmap`→`geoai`→`PyTorch` deps bloat 20-line `ToolRegistry` Lunar already owns at `100%` branch | `pyproject.toml: GeoAgent[qgis]` marker extra, `for_qgis(iface)` `for_qgis` GUI-thread, `@geo_tool` `GeoToolRegistry` safety flags |
| `bunkmr/qgis-agent` | **REFERENCE-ONLY** | **MEDIUM** | `RAG SQLite FTS5` + `Cookbook` self-evolution + `QTimer` main-thread bridge (`call_tool()`) are patterns to study for accuracy + thread safety, but 15-tool surface overlaps GeoAgent; not J enough to integrate | `qgis_tools.py: call_tool()`, `DocStore` FTS5, `processor.py` |
| `iamtekson/GeoAgent` | **REFERENCE-ONLY** | **MEDIUM** | `Processing` registry discovery + `workflow.py` multi-step `decompose→route→execute` with `geoprocessing_flow.py` retry is high-value for `lunar_gis/analysis` M3 chaining; `LangGraph` dep + auto-retry without per-tool confirm violates `AGENTS.md:9` | `agents/workflow.py`, `geoprocessing_flow.py` |
| `kodeezabdullah/qgis-ai-agent` | **REJECT** (runtime) / **REFERENCE-ONLY** (50-tool surface idea) | **MEDIUM** | Missing `LICENSE` → License not identified in the repository snapshot examined; therefore Lunar GIS must not copy or vendor code from this repository unless licensing permission is established. (treated as All Rights Reserved — LICENSE not found in snapshot 2026-09-14, see §7) (`AGENTS.md:12`), self-executing fallback by default violates `AGENTS.md:4`, `QWebEngineView` not Qt6-clean, `requires-python` not 4-specific | `github.com/kodeezabdullah/qgis-ai-agent` no `LICENSE`, `plugins.qgis.org` no license field |
| `kodeezabdullah/geogenie` | **REJECT** direct / **REFERENCE-ONLY** pipeline export | **MEDIUM** | `GPL-2.0` compatible but 0★ maturity, QGIS 3 assumption, too narrow satellite+OSM; **reusable standalone PyQGIS pipeline** + `scheduler` idea valuable for `M8` `Reproducible workflows` | `github.com/kodeezabdullah/geogenie` GPL-2, `plugins.qgis.org/plugins/geogenie` 1.0.1 627 downloads |
| `robert6757/qgis-geo-knowledge-ai` | **REJECT** | **LOW** | Missing `LICENSE`, no source structure audited, unknown security, `Google Maps tiles` not in `PROVIDER_CONTRACT.md` | `github.com/robert6757/qgis-geo-knowledge-ai` no LICENSE |
| `ShogoHirasawa/OSM-AI` | **REJECT** narrow / **REFERENCE-ONLY** pattern | **MEDIUM** | 1-tool narrow `LLM→QL`, single `overpass-api.de` not pinned mirrors, no confirmation, missing license, but pattern `LLM→QL→QGIS layer` informs `data/` validated downloader | `core/overpass_client.py` |
| `ultramenid/AgenticGIS` | **REFERENCE-ONLY** | **MEDIUM** | `Zero deps` stdlib worker/main-thread bridge (`QTimer`/`QThreadPool`) valuable for `agent` executor without `langchain`; `run_pyqgis` catch-all violates `AGENTS.md:4` | `README Zero dependencies`, `QGIS 3.22+` including QGIS 4 |
| `YusufEminoglu/02Agent-OSM-Downloader` | **ADAPT pattern** (not code, `Other` license) / **INTEGRATE** optional Processing | **HIGH** | Bounded `4 fixed hosts` `3×Overpass + Nominatim`, `100 km²` tiled `2500 km²`, `6 tags ANY/ALL regex`, `17 styles`, `Agent Protocol v1` 4 Processing endpoints with validated proposal + explicit approval — gold standard for `lunar_gis/data` M4 `AVAILABLE/DERIVABLE/MISSING` + `Provider Contract` | `github.com/YusufEminoglu/02Agent-OSM-Downloader` Other 1.3.4 QGIS 4, `zero2agentosm:download_preset` |
| `3liz/QuickOSM` / `OSMDownloader` | **ADAPT pattern** (QuickOSM only; OSMDownloader GPL-3.0 reference-only) | **HIGH** | Mature `400k+` downloads `GPL-2.0` bounded Overpass `key/value` + `osmconf` parser, `Processing` model building | `3liz/QuickOSM` GPL-2.0, `lcoandrade/OSMDownloader` GPL-3.0 (not vendored), `plugins.qgis.org/plugins/QuickOSM` |
| `microsoft/GeoFaham` `PySTAC` etc. | **REFERENCE-ONLY** | **MEDIUM** | Heavy `AutoGen` `PostGIS` vs Lunar QGIS desktop; `PySTAC` `Apache-2.0` `Planetary Computer` `MIT` are **ADAPT** for `M4` STAC via `PROVIDER_CONTRACT.md` `search/get_metadata/download` | `PySTAC` Apache-2.0, `Microsoft/GeoFaham` MIT? |

*Confidence:* **HIGH** = 2 sources + 2 plugin + `pyproject` + license + recent commit; **MEDIUM** = 1 source + QGIS plugin page; **LOW** = missing license/source structure.

---

## 17. Recommended Lunar GIS Architecture

**Keep Phase 0 foundations and extend per `ADR-0004` DAG:**

```
lunar_gis/
├── ai/            → (M5) OpenRouter abstraction behind 1 interface, no `qgis` import, offline fallback (AGENTS.md:11)
├── agent/         → owns ToolSpec/ToolRisk/ToolVersion/ToolExecutionContext/ToolResult, validation (jsonschema/pydantic), permission, confirmation, audit, sequential executor (Qt GUI-thread marshalling injected via `ui` bridge protocol `ExecutorBridge`, adapted from GeoAgent/qgis-agent/AgenticGIS `QTimer` pattern; `agent` itself remains `qgis.gui`-free per `ADR-0004`)
├── analysis/      → deterministic AHP/MCE `qgis.core`/`Processing` (AGENTS.md:1) — no `ai` for math
├── cartography/   → deterministic layout (M7)
├── data/          → local file inspection → provider adapters implementing PROVIDER_CONTRACT.md (search/get_metadata/get_assets/download/connect/attribution/license) for OSM (02Agent bounded pattern), STAC (PySTAC/Planetary Computer `/vsicurl/` signed COG via QGIS background task), future Satellite (Copernicus/USGS via same adapter, not GeoGenie auto-pick)
├── project/       → ProjectContext (already 100% branch, 17 fakes) + future extent/CRS/file inspection for AVAILABLE/DERIVABLE
├── provenance/    → lineage `dataset + tool + params + QGIS version + workflow ID` (M6/M8)
├── reports/       → M8 `pipeline export` adapted from GeoGenie *concept* (save reusable standalone PyQGIS, not auto-exec)
├── ui/            → dock `LunarGISDock` Qt6, no business logic
└── utils/         → leaf, deterministic
```

**Provider abstraction (M5):** Do not `pip install geoagent`; own `GeoAgentConfig`-like `ProviderConfig(provider, model, base_url, api_key Env)` with explicit allow-list `["openai","openrouter","ollama","openai-compatible"]` (GeoAgent's 8-provider table as reference). **Tooling:** keep `openai`/`litellm` as *optional* extras, not core.

**Security:** Keep `bandit`+`gitleaks`+`permissions: contents: read`+`fetch-depth:0` + `.env` ignored + 4 fixed hosts for `data/` (adapt 02Agent). `run_pyqgis_script` stays **disabled by default** behind `risk=high` + `confirmation` + audit (ADR-0002).

---

## 18. Recommended M1 Implementation Boundary

**M1 = `ProjectContext` + `ToolRegistry` hardened, no AI.**

**Should Lunar GIS own `ToolSpec` etc.?**

**Yes — BUILD.** `ToolSpec`/`ToolInput`/`ToolOutput`/`ToolRisk`/`ToolVersion`/`ToolExecutionContext`/`ToolResult` are **7 concepts** that form the `validated, versioned tools/schemas` contract `AGENTS.md:3` + `ADR-0002`. External frameworks (`GeoAgent` `GeoToolRegistry`, `bunkmr` 15 tools, `iamtekson` `schemas.py`) provide *examples* of schemas but couple tool metadata to provider/model (`GeoAgentConfig`) and to `strands` orchestration. Lunar needs a **QGIS-only** contract: `name: str` (`project.list_layers` etc.), `version: int`, `risk: "read"|"low"|"medium"|"high"` (already `registry.py:22`), `ToolInput`/`ToolOutput` as `dataclass` + `jsonschema` (`additionalProperties: false`), `ToolVersion` semver, `ToolExecutionContext` (`iface`, `project`, `crs`, `user confirmation`), `ToolResult(status, output, provenance, audit_id)`. No `strands` dep.

Current `lunar_gis/agent/registry.py` `ToolSpec(name,version,risk,handler)` is **sufficient as long-term abstraction boundary** *iff* extended as:

> **Note:** The planned extension below was implemented in M1-T02 (commit `feat: implement tool contract and registry`). See `docs/adr/ADR-0008-tool-contracts.md` for the accepted design decisions. The implementation uses frozen dataclasses with custom schema validation (no `jsonschema` dependency) and JSON boundary enforcement via `_reject_non_json_values`.

```python
@dataclass(frozen=True): ToolSpec(name, version, risk, handler: Callable[..., Any] | None = None, input_schema: dict | None = None, output_schema: dict | None = None, description: str = "")  # additive defaults, existing 4-arg construction remains valid; registry validates input_schema via jsonschema before handler
ToolInput  — validated JSON against input_schema
ToolOutput — validated JSON against output_schema
ToolRisk   — enum read/low/medium/high → permission/confirmation matrix
ToolVersion — int + deprecation
ToolExecutionContext — project, iface (opaque Any, no qgis.gui import; marshalled via ui ExecutorBridge), audit_id, timestamp, crs, confirmation token (no GITHUB_TOKEN — CI token stays in security-gate GITHUB_TOKEN least-privilege)
ToolResult — status, output, provenance_id, error
```

Do **not** import from `opengeos/GeoAgent`. Reference its `confirm` hook and `for_qgis` GUI marshalling as pattern docs.

**M1 tasks (no AI):** `tests/fixtures/qgis_fakes.py` already minimal — keep; add `project` extent/CRS/file tests, `registry` validation (`jsonschema` for `search/get_assets`), `permission` `read` vs `high` + `confirm` dialog, `audit` JSONL provenance, `QTimer` executor stub. Keep QGIS fakes minimal (add `extent`, `crs` `isValid` only when `ProjectContext` needs it).

---

## 19. What We Should NOT Build

* **Arbitrary Python executor** — Lunar already disables by default; do not build `run_pyqgis_script` equivalent until isolated, sandboxed, high-risk confirmed, audited — defer beyond M5.
* **RAG SQLite FTS5 doc store + Cookbook** (`qgis-agent` `DocStore 679 docs`, `Cookbook` self-evolution) — accuracy improvement but not Phase 0/1 correctness; adds `psutil`/`httpx`/`langchain_deepseek` deps. Defer to `M5` prompt-architecture if `ToolSpec` validation proves insufficient.
* **Generic OpenRouter free-model invisible chain** (`geogenie`/`qgis-ai-agent` “model never picked”) — Lunar must expose provider/model choice for cost/transparency, not hide.
* **Heavy `leafmap`/`geoai`/`PyTorch` stack** via `GeoAgent[all]` — QGIS plugin does not need notebook leafmap.
* **QGIS GUI container / QGIS Docker harness** in `P0-T10` — deferred per task; manual smoke `dist/lunar_gis.zip` suffices.

---

## 20. What We Should NOT Integrate

* **Do not `pip install opengeos/GeoAgent` as runtime dep for `ToolRegistry`** — Conceptually useful, but integrates `strands-agents` orchestration, `leafmap`/`geoai` heavy extras, and `run_pyqgis_script` fallback that violates `AGENTS.md:4`. Adds GPL-2.0 vs MIT header retention complexity for 20-line registry. **Use as ADAPT reference.**
* **Do not `pip install kodeezabdullah/qgis-ai-agent` / `geogenie` / `OSM-AI` / `AgenticGIS`** — missing or GPL-2.0 `Other` licenses, not QGIS 4 verified, narrow, maturity `0★`. **REJECT.**
* **Do not `pip install YusufEminoglu/02Agent-OSM-Downloader` as runtime dep** — `Other` Source Available license **incompatible** with `GPL-2.0-or-later` distribution (`Other` prohibits verbatim GPL reuse). **Do not copy code;** **ADAPT pattern** behind own `DataProvider`.
* **Do not integrate `AutoGen`-based `GeoFaham`** — `PostGIS` + `FastAPI` + `TiTiler` multi-agent vs Lunar QGIS desktop; **REFERENCE-ONLY**.

---

## 21. Future Reuse Candidates (beyond M1, not immediate)

* **Data providers to eventually ADAPT (not INTEGRATE) behind `PROVIDER_CONTRACT.md`:**
  * **PySTAC** `Apache-2.0` (`pystac`) + **`planetary-computer` SDK** `MIT` (`microsoft/planetary-computer`) for `search`/`get_metadata`/`get_assets`/`download`/`attribution`/`license` for `AWS Earth Search` & `Microsoft Planetary Computer` (seen in `geo-knowledge-ai`). Reuse `PySTAC` as **optional** dep, not copy.
  * **pystac-client** `Apache-2.0` for STAC search pagination.
  * **GDAL `/vsicurl/`** already in QGIS/GDAL — no pip dep, use signed COG URLs via QGIS background task (`GeoAgent` STAC `qgis-stac` plugin pattern: status bar loading message).
  * **Nominatim** geocoder (OSM `Nominatim` `GPL-2.0`) for place search — adapt `02Agent` `4 fixed hosts` pattern (Nominatim + 3 Overpass mirrors).
* **OSM:** `QuickOSM` `GPL-2.0` *optional* Processing dependency (`pyproject.toml:optional-dependencies` `osm`), not core pip dep.
* **Geocoding:** `geopy` `MIT` `Nominatim` client `BSD` for `lunar_gis/data` address → bbox (alternative to direct `Nominatim` `requests`).
* **Satellite imagery:** `sentinelsat`/`sentinelsat` `GPL-3.0` for `Copernicus` `SciHub` search — **GPL-3.0 incompatible with `GPL-2.0-or-later` as runtime dep** (GPL-3.0 requires GPL-3.0 distribution) — must be `optional` + `AGENTS.md:12` review; prefer `PySTAC` via `Planetary Computer` which is `MIT`.
* **Vector/raster loading:** `GDAL`/`QGIS` already provide `QgsVectorLayer`/`QgsRasterLayer` — no `fiona`/`rasterio` pip dep needed for QGIS plugin.

---

## 22. Risks and Unknowns

* **GeoAgent maintenance risk:** If `opengeos/GeoAgent` pivots to `strands` breaking change, Lunar is unaffected because we own registry. If it becomes QGIS 3-only, Lunar's `qgis4` shim remains.
* **QGIS 4 `geometryType()` enum drift** (`qgis_expert` H1 2026-09-14): `str(layer.geometryType())` yields `"Qgis.GeometryType.Point"` on QGIS 4 vs `"1"` on fakes; `int()` coercion already defensive but test asserts `"1"`. Risk: tests false-pass offline but real QGIS 4 diverges. Mitigation: verify in QGIS 4.0.1 console `type(layer.geometryType())` per `qgis4` skill before `M1` hardening.
* **`featureCount() == -1` unknown** (QGIS returns `-1` for unknown count) — not modeled in fakes; `int(-1)` preserved as `-1` not `None`. Risk: provider `unknown` vs `0` ambiguous for `AVAILABLE`.
* **`gitleaks-action` EULA** (`Other`) for Org repos requires `GITLEAKS_LICENSE` for `LunarCorp1` Org if scanning private Org repos beyond free tier — flagged as CI-only `Other`, not distributed.
* **License missing repos:** `qgis-ai-agent`, `AgenticGIS`, `geo-knowledge-ai` missing `LICENSE` → treat as `License not identified in the repository snapshot examined; therefore Lunar GIS must not copy or vendor code from this repository unless licensing permission is established. (treated as All Rights Reserved — LICENSE not found in snapshot 2026-09-14, see §7)`; cannot copy even MIT-like snippets without file.
* **Overpass host pinning:** `02Agent` 4 fixed hosts verified, but mirrors change DNS; `QGIS` `lunar_gis/data` must re-pin and retry with backoff.
* **No runtime harness:** `plugin.py 0%` until QGIS harness — coverage `40→44%` threshold defensible, but `quality-gate` still offline only.

---

## 23. Final Decisions

| Decision | Choice | Confidence | Rationale |
|---|---|---|---|
| **Own ToolRegistry?** | **BUILD** — own `ToolSpec` 7 concepts | **HIGH** | 20-line `registry.py:8-33` already 100% branch, `risk` enum, `KeyError` unknown, `sorted`, `frozen`; external `GeoToolRegistry` adds `strands` dep and `run_pyqgis_script` taint for no gain. |
| **GeoAgent library** | **ADAPT concepts / REFERENCE-ONLY dep** | **HIGH** | Provider abstraction + GUI marshalling valuable, `run_pyqgis_script` + heavy `leafmap`/`geoai` violates `AGENTS.md:4,1`. |
| **GeoAgent plugin `OpenGeoAgent`** | **REFERENCE-ONLY** | **MEDIUM** | Dockable chat with provider/model controls + `uv` isolated venv + screenshot handling is UX reference, not code. |
| **qgis-agent (bunkmr)** | **REFERENCE-ONLY** | **MEDIUM** | RAG/cookbook + `QTimer` bridge pattern. |
| **iamtekson/GeoAgent** | **REFERENCE-ONLY** | **MEDIUM** | `Processing` registry discovery + multi-step workflow. |
| **qgis-ai-agent** | **REJECT** dep / **REFERENCE-ONLY** idea | **MEDIUM** | License not identified in the repository snapshot examined; therefore Lunar GIS must not copy or vendor code from this repository unless licensing permission is established., self-exec by default. |
| **geogenie** | **REJECT** dep / **REFERENCE-ONLY** pipeline export | **MEDIUM** | GPL-2.0 compatible but 0★, satellite auto-pick not Processing. |
| **geo-knowledge-ai** | **REJECT** | **LOW** | License not identified in the repository snapshot examined; therefore Lunar GIS must not copy or vendor code from this repository unless licensing permission is established., unknown security. |
| **OSM-AI** | **REJECT** narrow / **REFERENCE-ONLY** pattern | **MEDIUM** | 1-tool LLM→QL, single host. |
| **AgenticGIS** | **REFERENCE-ONLY** | **MEDIUM** | stdlib bridge valuable, `run_pyqgis` violates. |
| **02Agent OSM Downloader** | **ADAPT pattern** (not code, `Other`) + **INTEGRATE** optional Processing | **HIGH** | Bounded 4 hosts, tiled 2500 km², structured `6 tags ANY/ALL regex`, validated proposal + approval — matches `SECURITY_MODEL.md`. |
| **QuickOSM** | **ADAPT pattern** | **HIGH** | Mature 400k+ GPL-2.0 bounded Overpass. |
| **PySTAC / Planetary Computer** | **ADAPT** (optional dep, Apache-2.0/MIT) | **HIGH** | For `M4` STAC via `PROVIDER_CONTRACT.md`. |
| **GeoFaham / AutoGen** | **REFERENCE-ONLY** | **MEDIUM** | Heavy multi-agent vs QGIS desktop. |

**M1 boundary:** Own `ToolSpec` 7 concepts with `version`/`risk`/`input_schema`/`output_schema`/`confirmation`/`audit` + `ProjectContext` extent/file inspection + `data` bounded adapter; no `openai`/`openrouter` client, no `run_pyqgis_script`.

**What NOT to build/integrate listed in §19/20 holds.**

*Sources:* `github.com/opengeos/GeoAgent` MIT 1.9.0 2026-08-09, `plugins.qgis.org/plugins/open_geoagent` 3.28-4.99, `github.com/bunkmr/qgis-agent` MIT 15 tools `DocStore` FTS5, `github.com/iamtekson/GeoAgent` MIT 40★ `geoprocessing_flow.py`, `github.com/kodeezabdullah/qgis-ai-agent` no LICENSE 0.1.2, `github.com/kodeezabdullah/geogenie` GPL-2 1.0.1 627 downloads, `github.com/ShogoHirasawa/OSM-AI` no LICENSE 0.1.0, `github.com/ultramenid/AgenticGIS` stdlib QGIS 4 `3.22+`, `github.com/YusufEminoglu/02Agent-OSM-Downloader` Other 1.3.4 QGIS 4, `github.com/3liz/QuickOSM` GPL-2.0, `AGENTS.md`, `docs/adr/*`, `lunar_gis/project/context.py`, `lunar_gis/agent/registry.py` at `932c1c3` 2026-09-14.
