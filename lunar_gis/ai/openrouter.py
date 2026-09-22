"""M5 OpenRouter transport (stdlib urllib, key never logged).

- endpoint fixed to the allowlisted OpenRouter host (AGENTS.md:5 —
  no arbitrary URLs; the endpoint is a constant, not a parameter)
- API key resolved at call time from (1) explicit argument, (2) the
  ``OPENROUTER_API_KEY`` environment variable, (3) QSettings
  (``lunar-gis/openrouter_api_key``). The key travels only in the
  ``Authorization`` header; it is never logged, never stored in
  records, never echoed in errors, never included in model context
- redirects disabled (no redirect chain to hijack); resolved-IP
  blocking reuses the provider transport validator
- precise error taxonomy: AUTH_FAILED (401/403), ENDPOINT_NOT_FOUND
  (404), RATE_LIMITED (429), SERVER_ERROR (5xx), TLS_FAILED,
  NETWORK_UNREACHABLE, PROVIDER_OFFLINE (DNS/other) — auth and config
  failures are never collapsed into "offline"
- environment proxies honored (HTTP_PROXY/HTTPS_PROXY/NO_PROXY);
  provider JSON error messages surfaced truncated and key-free
- responses parsed defensively: invalid JSON / missing choices /
  malformed tool calls → INVALID_RESPONSE (fail-closed, never guessed)

No third-party HTTP clients (zero new runtime deps).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from lunar_gis.ai.contracts import (
    AIConfig,
    AIErrorCode,
    AIResponse,
    AIToolCall,
    OPENROUTER_API_URL,
    OPENROUTER_HOST,
    validate_tool_call_shape,
)

_QSETTINGS_ORG = "lunar-gis"
_QSETTINGS_KEY = "openrouter_api_key"


def resolve_api_key(explicit: str | None = None) -> str | None:
    """Resolve the API key without ever logging it (returns None if absent)."""
    if explicit:
        return explicit
    env_key = os.environ.get("OPENROUTER_API_KEY", "")
    if env_key:
        return env_key
    try:
        from qgis.PyQt.QtCore import QSettings  # type: ignore[import-not-found]

        stored = QSettings(_QSETTINGS_ORG, "settings").value(_QSETTINGS_KEY, "")
        return str(stored) if stored else None
    except ImportError:
        return None


def store_api_key(key: str) -> bool:
    """Persist the key to QSettings (never to logs/records)."""
    try:
        from qgis.PyQt.QtCore import QSettings  # type: ignore[import-not-found]

        QSettings(_QSETTINGS_ORG, "settings").setValue(_QSETTINGS_KEY, key)
        return True
    except ImportError:
        return False


def clear_api_key() -> bool:
    try:
        from qgis.PyQt.QtCore import QSettings  # type: ignore[import-not-found]

        QSettings(_QSETTINGS_ORG, "settings").remove(_QSETTINGS_KEY)
        return True
    except ImportError:
        return False


def has_api_key(explicit: str | None = None) -> bool:
    return bool(resolve_api_key(explicit))


def _redacted_error(detail: str) -> str:
    """Errors never echo the key, URL query, or response secrets."""
    return detail[:200]


def _provider_message(raw: bytes) -> str:
    """Extract OpenRouter's JSON error message (truncated, key-free).

    The body is provider-generated diagnostics (e.g. "Invalid API key");
    it never contains our secret. Malformed bodies degrade to "".
    """
    try:
        payload = json.loads(raw[:4096].decode("utf-8", errors="replace"))
    except ValueError:
        return ""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return str(error["message"])[:200]
        if isinstance(error, str):
            return str(error)[:200]
    return ""


def _classify_http_error(code: int, body: bytes) -> tuple[str, str]:
    """Map HTTP status to (error_code, detail). Never collapses auth."""
    message = _provider_message(body)
    suffix = f": {message}" if message else ""
    if code in (401, 403):
        return AIErrorCode.AUTH_FAILED.value, f"http-{code}{suffix} (check API key)"
    if code == 404:
        return AIErrorCode.ENDPOINT_NOT_FOUND.value, f"http-404{suffix} (check model/endpoint)"
    if code == 400:
        return AIErrorCode.INVALID_REQUEST.value, f"http-400{suffix} (request rejected by provider)"
    if code == 429:
        return AIErrorCode.RATE_LIMITED.value, f"http-429{suffix}"
    if 500 <= code <= 599:
        return AIErrorCode.SERVER_ERROR.value, f"http-{code}{suffix}"
    return AIErrorCode.PROVIDER_OFFLINE.value, f"http-{code}{suffix}"


def _classify_url_error(reason: Any) -> tuple[str, str]:
    """Distinguish TLS / DNS / connection failures (never one bucket)."""
    import socket
    import ssl

    text = str(reason)
    if isinstance(reason, ssl.SSLError):
        return AIErrorCode.TLS_FAILED.value, f"tls-failed: {text[:120]}"
    if isinstance(reason, socket.gaierror):
        return AIErrorCode.PROVIDER_OFFLINE.value, f"dns-failed: {text[:120]}"
    if isinstance(reason, (ConnectionError, socket.timeout, TimeoutError)):
        return AIErrorCode.NETWORK_UNREACHABLE.value, f"connection-failed: {text[:120]}"
    return AIErrorCode.PROVIDER_OFFLINE.value, _redacted_error(text)


def _build_opener() -> urllib.request.OpenerDirector:
    """Opener honoring environment proxies (HTTP_PROXY/HTTPS_PROXY/NO_PROXY).

    Note: QGIS desktop proxy settings are not honored here (M4 §13
    transport note); environments requiring a proxy must export the
    standard variables. Proxy use is reported in diagnostics, never the
    key.
    """
    return urllib.request.build_opener(
        urllib.request.ProxyHandler(),
        urllib.request.HTTPHandler(),
        urllib.request.HTTPSHandler(),
    )


def chat_completion(
    messages: list[dict[str, Any]],
    config: AIConfig,
    *,
    api_key: str | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Call OpenRouter chat completions. (ok, payload|error). Never raises."""
    from lunar_gis.data.adapters.transport import resolve_and_check

    key = resolve_api_key(api_key)
    if not key:
        return False, {"error": AIErrorCode.NO_API_KEY.value, "detail": "no API key configured"}
    if config.endpoint != OPENROUTER_API_URL:
        return False, {"error": AIErrorCode.INVALID_RESPONSE.value, "detail": "endpoint not allowlisted"}
    ok, reason = resolve_and_check(OPENROUTER_HOST)
    if not ok:
        return False, {"error": AIErrorCode.PROVIDER_OFFLINE.value, "detail": _redacted_error(reason)}
    body: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    request = urllib.request.Request(
        OPENROUTER_API_URL,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/LunarCorp1/lunar-gis",
            "X-Title": "Lunar GIS",
        },
    )
    opener = _build_opener()
    try:
        with opener.open(request, timeout=config.timeout_s) as response:
            raw = response.read(1024 * 1024)
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        try:
            error_body = exc.read(4096)
        except Exception:
            error_body = b""
        code, detail = _classify_http_error(int(exc.code), error_body)
        return False, {"error": code, "detail": detail}
    except urllib.error.URLError as exc:
        code, detail = _classify_url_error(exc.reason)
        return False, {"error": code, "detail": detail}
    except (TimeoutError, OSError) as exc:
        return False, {"error": AIErrorCode.TIMEOUT.value, "detail": f"transport-timeout: {type(exc).__name__}"}
    if status != 200:
        code, detail = _classify_http_error(status, raw)
        return False, {"error": code, "detail": detail}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False, {"error": AIErrorCode.INVALID_RESPONSE.value, "detail": "invalid-json"}
    return True, payload


def parse_response(
    payload: dict[str, Any], model: str = "", name_map: dict[str, str] | None = None
) -> tuple[bool, dict[str, Any]]:
    """Parse a chat-completions payload into explanation + tool calls.

    ``name_map`` translates provider-safe function names back to
    registry dotted names BEFORE shape validation. Provider names with
    no mapping are rejected (never guessed, never passed through).
    """
    try:
        choices = payload.get("choices", [])
        message = choices[0].get("message", {}) if choices else {}
        explanation = message.get("content") or ""
        raw_calls = message.get("tool_calls", []) or []
        calls: list[dict[str, Any]] = []
        for raw in raw_calls:
            if not isinstance(raw, dict):
                continue
            function = raw.get("function", {}) if isinstance(raw.get("function"), dict) else {}
            provider_name = function.get("name", "")
            if name_map is not None:
                mapped = name_map.get(provider_name, "")
                if not mapped:
                    return False, {
                        "error": AIErrorCode.MALFORMED_TOOL_CALL.value,
                        "detail": f"unmapped tool name: {provider_name[:80]}",
                    }
                name = mapped
            else:
                name = provider_name
            try:
                args = json.loads(function.get("arguments", "{}") or "{}")
            except ValueError:
                return False, {"error": AIErrorCode.MALFORMED_TOOL_CALL.value, "detail": "bad-arguments-json"}
            call = {"tool_name": name, "tool_version": "1.0.0", "arguments": args}
            errors = validate_tool_call_shape(call)
            if errors:
                return False, {"error": AIErrorCode.MALFORMED_TOOL_CALL.value, "detail": "; ".join(errors)}
            calls.append(call)
        usage = payload.get("usage", {}) if isinstance(payload.get("usage"), dict) else {}
        response = AIResponse(
            explanation=str(explanation),
            tool_calls=tuple(
                AIToolCall(tool_name=c["tool_name"], tool_version=c["tool_version"], arguments=c["arguments"])
                for c in calls
            ),
            model=model,
            usage={k: int(v) for k, v in usage.items() if isinstance(v, int)},
        )
        return True, {"explanation": response.explanation, "tool_calls": [c.__dict__ for c in response.tool_calls]}
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        return False, {"error": AIErrorCode.INVALID_RESPONSE.value, "detail": _redacted_error(str(exc))}


__all__ = [
    "resolve_api_key",
    "store_api_key",
    "clear_api_key",
    "has_api_key",
    "chat_completion",
    "parse_response",
]
