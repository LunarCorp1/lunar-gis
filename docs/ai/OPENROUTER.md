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
| `INVALID_RESPONSE` | bad JSON / malformed payload | **no — hard error** |

Auth/config errors surface in the Assistant as `AI request failed:
AUTH_FAILED: http-401: <provider message> (check API key)` with
guidance — never as a misleading "Offline plan (no AI configured)".

## Environment

- `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` are honored. QGIS desktop
  proxy settings are not (documented limitation, M4 §13).
- Live LLM calls never run in CI (mocked transport only).
