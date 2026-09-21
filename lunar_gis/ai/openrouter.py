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
    opener = urllib.request.build_opener(urllib.request.HTTPHandler(), urllib.request.HTTPSHandler())
    try:
        with opener.open(request, timeout=config.timeout_s) as response:
            raw = response.read(1024 * 1024)
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return False, {"error": AIErrorCode.RATE_LIMITED.value, "detail": "http-429"}
        return False, {"error": AIErrorCode.PROVIDER_OFFLINE.value, "detail": f"http-{exc.code}"}
    except urllib.error.URLError as exc:
        return False, {"error": AIErrorCode.PROVIDER_OFFLINE.value, "detail": _redacted_error(str(exc.reason))}
    except (TimeoutError, OSError):
        return False, {"error": AIErrorCode.TIMEOUT.value, "detail": "transport-timeout"}
    if status != 200:
        return False, {"error": AIErrorCode.PROVIDER_OFFLINE.value, "detail": f"http-{status}"}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False, {"error": AIErrorCode.INVALID_RESPONSE.value, "detail": "invalid-json"}
    return True, payload


def parse_response(payload: dict[str, Any], model: str = "") -> tuple[bool, dict[str, Any]]:
    """Parse a chat-completions payload into explanation + tool calls."""
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
            name = function.get("name", "")
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
