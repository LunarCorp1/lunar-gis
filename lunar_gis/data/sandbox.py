"""Sandbox lifecycle: audit + orphan sweep (QGIS-free, stdlib only).

Acquisitions create one sandbox per download (`lunar-acquire-*`,
`lunar-e2e-*`, `lunar-transform-*` prefixes). Failed or abandoned runs
leave orphans behind; the sweep removes prefix-matched directories
older than a retention age, records what it did (audit-friendly
return), and never touches anything else.

Only single-level directory names under the given root are considered;
symlinks are never followed (realpath prefix check) and non-matching
names are left alone.
"""

from __future__ import annotations

import os
import time
from typing import Any

SANDBOX_PREFIXES: tuple[str, ...] = ("lunar-acquire-", "lunar-e2e-", "lunar-transform-", "lunar-loadtest-")
DEFAULT_RETENTION_S: float = 7 * 24 * 3600
# In-flight protection: never remove a sandbox younger than this, even on
# explicit clean (a download may be writing into it right now).
ACTIVE_FLOOR_S: float = 60.0


def _dir_size(root: str) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                continue
    return total


def sandbox_usage(root: str) -> dict[str, Any]:
    """Measure Lunar GIS sandbox storage under root (no mutation)."""
    count = 0
    total = 0
    try:
        entries = os.listdir(root)
    except OSError:
        return {"sandbox_count": 0, "bytes": 0, "root": root}
    for name in entries:
        if not name.startswith(SANDBOX_PREFIXES):
            continue
        path = os.path.join(root, name)
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                count += 1
                total += _dir_size(path)
        except OSError:
            continue
    return {"sandbox_count": count, "bytes": total, "root": root}


def sweep_sandboxes(root: str, retention_s: float = DEFAULT_RETENTION_S, now: float | None = None) -> dict[str, Any]:
    """Remove orphan sandboxes older than retention_s. Returns an audit record."""
    import shutil

    moment = now if now is not None else time.time()
    removed: list[str] = []
    freed = 0
    kept = 0
    try:
        entries = os.listdir(root)
    except OSError as exc:
        return {"ok": False, "error": f"unreadable-root: {exc}", "removed": [], "freed_bytes": 0, "kept": 0}
    real_root = os.path.realpath(root)
    for name in entries:
        if not name.startswith(SANDBOX_PREFIXES):
            continue
        path = os.path.join(root, name)
        try:
            if os.path.islink(path) or not os.path.isdir(path):
                continue
            if os.path.realpath(path) != os.path.join(real_root, name):
                continue
            age = moment - os.path.getmtime(path)
            if age < max(retention_s, ACTIVE_FLOOR_S):
                kept += 1
                continue
            freed += _dir_size(path)
            shutil.rmtree(path, ignore_errors=False)
            removed.append(name)
        except OSError:
            kept += 1
            continue
    return {"ok": True, "removed": sorted(removed), "freed_bytes": freed, "kept": kept}


def format_bytes(count: int) -> str:
    units = ("bytes", "KB", "MB", "GB")
    value = float(max(0, count))
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "bytes" else f"{int(value)} bytes"
        value /= 1024
    return f"{value:.1f} GB"


__all__ = [
    "SANDBOX_PREFIXES",
    "DEFAULT_RETENTION_S",
    "ACTIVE_FLOOR_S",
    "sandbox_usage",
    "sweep_sandboxes",
    "format_bytes",
]
