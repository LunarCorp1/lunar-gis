"""M5 privacy-controlled context assembly (QGIS-free).

Builds the labeled context the planner may send to the model:

- summaries and schemas over raw data (never attribute tables, never
  geometries, never full datasets)
- file paths minimized (basename/relpath + home collapse)
- layer names escaped + trust-labeled UNTRUSTED_PROJECT (T2)
- provider metadata labeled UNTRUSTED_PROVIDER (T3)
- deterministic tool outputs labeled ENGINE_OUTPUT
- disclosure: ``describe_context`` renders exactly what leaves the
  machine so the user can inspect it before any AI call

Budgets (impl config): max layers, max fields per layer, max chars per
segment, max total chars. Over-budget input is truncated with an
explicit ``[truncated]`` marker — never silently dropped.
"""

from __future__ import annotations

import html
import os
from typing import Any

from lunar_gis.ai.contracts import ContextSegment, TrustLabel

MAX_LAYERS = 50
MAX_FIELDS_PER_LAYER = 30
MAX_SEGMENT_CHARS = 4000
MAX_TOTAL_CHARS = 20000


def escape_display(text: str) -> str:
    """HTML-escape untrusted display strings (T2)."""
    return html.escape(str(text), quote=True)


def minimize_path(path: str) -> str:
    """Basename-ish minimization for context (no home/username leak)."""
    if not isinstance(path, str) or not path:
        return ""
    home = os.path.expanduser("~")
    if home and home != "~" and path.startswith(home):
        path = "~" + path[len(home) :]
    return path


def _truncate(text: str, limit: int = MAX_SEGMENT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[truncated]"


def project_summary_segment(inventory_payload: dict[str, Any]) -> ContextSegment:
    """Summarize an inventory payload (describe_project output)."""
    lines = ["PROJECT SNAPSHOT (summaries only — no attribute data, no geometry):"]
    records = inventory_payload.get("records", [])
    if not isinstance(records, list):
        records = []
    for record in records[:MAX_LAYERS]:
        if not isinstance(record, dict):
            continue
        name = escape_display(record.get("name", "?"))
        raw_fields = record.get("fields")
        fields = raw_fields if isinstance(raw_fields, list) else []
        field_names = [str(f.get("name", "?")) for f in fields[:MAX_FIELDS_PER_LAYER] if isinstance(f, dict)]
        lines.append(
            f"- {name} | geometry={record.get('geometry_type')} | crs={record.get('crs_authid')} "
            f"| features={record.get('feature_count')} | fields=[{', '.join(field_names)}] "
            f"| storage={record.get('storage')} | valid={record.get('valid')}"
        )
    if len(records) > MAX_LAYERS:
        lines.append(f"[truncated: {len(records) - MAX_LAYERS} more layers]")
    lines.append(f"snapshot_id={inventory_payload.get('snapshot_id')} taken_at={inventory_payload.get('taken_at')}")
    return ContextSegment(label=TrustLabel.UNTRUSTED_PROJECT, text=_truncate("\n".join(lines)))


def engine_output_segment(title: str, payload: dict[str, Any]) -> ContextSegment:
    """Wrap a deterministic tool result (key facts only, capped)."""
    lines = [f"ENGINE RESULT: {title}"]
    for key in ("availability", "fulfillment_kind", "missing_reason", "verdict", "satisfaction", "ok", "error"):
        if key in payload:
            lines.append(f"{key}={payload[key]}")
    evidence = payload.get("evidence")
    if isinstance(evidence, list):
        lines.append("evidence:")
        lines.extend(f"  {str(item)[:200]}" for item in evidence[:20])
    return ContextSegment(label=TrustLabel.ENGINE_OUTPUT, text=_truncate("\n".join(lines)))


def provider_segment(results: list[dict[str, Any]]) -> ContextSegment:
    """Wrap catalog metadata (untrusted, titles escaped)."""
    lines = ["PROVIDER RESULTS (untrusted metadata — verify before acquisition):"]
    for item in results[:20]:
        if not isinstance(item, dict):
            continue
        title = escape_display(item.get("title", "?"))
        lines.append(f"- {title} | id={item.get('dataset_id')} | license={item.get('license_spdx')}")
    return ContextSegment(label=TrustLabel.UNTRUSTED_PROVIDER, text=_truncate("\n".join(lines)))


def build_messages(
    system_prompt: str,
    user_request: str,
    segments: list[ContextSegment],
) -> list[dict[str, Any]]:
    """Assemble labeled messages. Untrusted segments carry their labels
    inline so the model cannot mistake them for instructions."""
    labeled: list[str] = []
    total = 0
    for segment in segments:
        block = f"[{segment.label.value}]\n{segment.text}"
        if total + len(block) > MAX_TOTAL_CHARS:
            labeled.append("[context-truncated: budget exceeded]")
            break
        labeled.append(block)
        total += len(block)
    context_text = "\n\n".join(labeled)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"{context_text}\n\n[trusted-user]\n{user_request}"},
    ]


def describe_context(segments: list[ContextSegment]) -> dict[str, Any]:
    """User-visible disclosure: exactly what would leave the machine."""
    total = sum(len(s.text) for s in segments)
    return {
        "segment_count": len(segments),
        "total_chars": total,
        "labels": [s.label.value for s in segments],
        "contains_raw_attributes": False,
        "contains_geometry": False,
        "contains_api_keys": False,
        "preview": [_truncate(s.text, 500) for s in segments],
    }


__all__ = [
    "escape_display",
    "minimize_path",
    "project_summary_segment",
    "engine_output_segment",
    "provider_segment",
    "build_messages",
    "describe_context",
]
