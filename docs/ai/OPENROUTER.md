# OpenRouter provider: configuration flow and error taxonomy

## Configuration flow (single source, read fresh per call)

```text
Settings tab → ApiKeyDialog → openrouter.store_api_key()
  → QSettings("lunar-gis", "settings") / "openrouter_api_key"
  → chat_completion → resolve_api_key()
  → (1) explicit arg, (2) OPENROUTER_API_KEY env, (3) QSettings (same coordinates)
```

Status (`ai_status`) and runtime (`plan_with_ai`) read the same source
on every call — there is no startup cache to go stale. A mismatch
between "API key configured: True" and provider errors therefore means
the key is present but rejected/unreachable, never that it is missing.

## Endpoint / model

- Endpoint (constant, not a parameter): `https://openrouter.ai/api/v1/chat/completions`
- Default model (config-overridable): `openai/gpt-4o-mini`
- Auth: `Authorization: Bearer <key>` header only; the key never appears
  in logs, errors, audit records, provenance, transcripts, or model context.

## Tool names on the wire

Registry tools use dot notation (`data.describe_project`) per the
ToolSpec contract, but OpenAI-style function names must match
`^[a-zA-Z0-9_-]+$` (no dots — the provider rejects dotted names with
HTTP 400). The planner therefore sends provider-safe names (first dot
→ underscore: `data_describe_project`) and maps returned calls back
against the live registry before shape validation. Unmapped names are
rejected as malformed; collisions fail closed at build time. The
registry itself never changes.

## Error taxonomy (`AIErrorCode`)

| Code | Meaning | Offline fallback? |
|---|---|---|
| `NO_API_KEY` | no key in any source | yes (offline plan, labeled) |
| `PROVIDER_OFFLINE` | DNS failure / unreachable host | yes |
| `NETWORK_UNREACHABLE` | connection refused/reset | yes |
| `TLS_FAILED` | certificate/TLS failure | yes |
| `TIMEOUT` | transport timeout | yes |
| `SERVER_ERROR` | HTTP 5xx | yes |
| `RATE_LIMITED` | HTTP 429 | yes |
| `AUTH_FAILED` | HTTP 401/403 (+ provider message) | **no — hard error** |
| `ENDPOINT_NOT_FOUND` | HTTP 404 | **no — hard error** |
| `INVALID_REQUEST` | HTTP 400 (e.g. provider-rejected payload) | **no — hard error** |
| `INVALID_RESPONSE` | bad JSON / malformed payload | **no — hard error** |

Auth/config errors surface in the Assistant as `AI request failed:
AUTH_FAILED: http-401: <provider message> (check API key)` with
guidance — never as a misleading "Offline plan (no AI configured)".

## Assistant loop (controller `plan_request`)

AI requests run at most 2 model rounds: model-proposed calls that need
no confirmation execute through the HIGH-only assistant executor and
their results feed the next round as `engine-output` segments; HIGH-risk
proposals return for dialog confirmation, never auto-executed. Prior
turns travel as labeled history (`trusted-user` / `assistant-history`,
last 6, budgeted). If the model returns empty text after executing
tools, the controller narrates what ran from evidence instead of
showing an empty message.

## Environment

- `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` are honored. QGIS desktop
  proxy settings are not (documented limitation, M4 §13).
- Live LLM calls never run in CI (mocked transport only).
