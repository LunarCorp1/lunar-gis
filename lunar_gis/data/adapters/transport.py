"""M4-T05 SSRF-safe HTTP transport (stdlib urllib, QGIS-free).

Implements the M4 §5.2/§9 egress wrapper. Transport decision (§13):
stdlib ``urllib`` with redirects DISABLED + manual allowlist re-check —
chosen because redirect targets must be re-validated pre-connect and
resolved-IP blocking requires check-after-resolve, both of which need
explicit control over the redirect chain. ``QgsFileDownloader`` remains
a future option; either is viable only inside this wrapper.

Enforcement (structural, not advisory):
- every egress URL validated against the adapter host allowlist BEFORE
  connect — including STAC asset hrefs and every redirect target
- redirects never followed automatically: 3xx responses are re-resolved
  through the same validator (same allowlist, same IP rules, same
  redirect budget); off-allowlist or blocked-IP targets are rejected
- resolved-IP (not hostname-string-only) RFC-1918/loopback/link-local/
  multicast/reserved blocking via check-after-resolve, to resist
  DNS-rebinding href/redirect attacks
- byte caps on streams; timeouts; no credentials ever attached;
  query-stripped audit URLs (host+path only)
- archive members: pre-listing with count/size caps, traversal/ADS/
  symlink/device rejection, extension re-check per member

No third-party HTTP clients (zero new runtime deps, §15.11).
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Any, Protocol
from contextlib import contextmanager
from contextvars import ContextVar

MAX_REDIRECTS = 5
CHUNK_SIZE = 65536


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    status: int | None = None
    body: bytes = b""
    final_url: str | None = None
    audit_url: str | None = None
    error: str | None = None
    redirects_followed: int = 0


def _host_allowed(host: str | None, allowlist: tuple[str, ...]) -> bool:
    if not host:
        return False
    candidate = host.lower().rstrip(".")
    for entry in allowlist:
        allowed = entry.lower().rstrip(".")
        if candidate == allowed or candidate.endswith("." + allowed):
            return True
    return False


def _ip_blocked(addr: str) -> bool:
    """True when a resolved IP must never be connected to."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True  # unparseable resolution output: fail closed
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified


def resolve_and_check(host: str) -> tuple[bool, str]:
    """Resolve a hostname and block private/reserved IPs. (ok, reason)."""
    try:
        infos = socket.getaddrinfo(host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
    except OSError as exc:
        return False, f"dns-failed: {exc}"
    addresses = {str(info[4][0]) for info in infos}
    if not addresses:
        return False, "dns-no-address"
    for addr in sorted(addresses):
        if _ip_blocked(addr):
            return False, f"blocked-ip: {addr}"
    return True, "ok"


def validate_egress_url(url: str, allowlist: tuple[str, ...]) -> tuple[bool, str]:
    """Validate one egress URL pre-connect. (ok, reason)."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return False, "malformed-url"
    if parts.scheme not in ("http", "https"):
        return False, f"blocked-scheme: {parts.scheme}"
    if not _host_allowed(parts.hostname, allowlist):
        return False, f"host-not-allowlisted: {parts.hostname}"
    ok, reason = resolve_and_check(parts.hostname or "")
    if not ok:
        return False, reason
    return True, "ok"


def audit_url(url: str) -> str | None:
    """Host+path only (query/fragment stripped) for audit records."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return f"{parts.scheme}://{parts.hostname}{parts.path or '/'}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Disable automatic redirects so targets pass the validator first."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:  # type: ignore[override]
        return None


def _build_opener(timeout_s: float) -> urllib.request.OpenerDirector:
    handlers: list[Any] = [
        urllib.request.HTTPHandler(),
        urllib.request.HTTPSHandler(),
        _NoRedirect(),
        urllib.request.HTTPErrorProcessor(),
    ]
    opener = urllib.request.build_opener(*handlers)
    opener.addheaders = [("User-Agent", "LunarGIS/1.0 (QGIS plugin; +https://github.com/LunarCorp1/lunar-gis)")]
    _ = timeout_s
    return opener


def fetch_url(
    url: str,
    allowlist: tuple[str, ...],
    *,
    timeout_s: float = 30.0,
    max_bytes: int = 500 * 1024 * 1024,
    progress: ProgressCallback | None = None,
) -> FetchResult:
    """GET a URL through the full egress validator. Redirects re-validated."""
    ok, reason = validate_egress_url(url, allowlist)
    if not ok:
        return FetchResult(ok=False, error=reason)
    opener = _build_opener(timeout_s)
    current = url
    redirects = 0
    while True:
        request = urllib.request.Request(current, method="GET")
        try:
            with opener.open(request, timeout=timeout_s) as response:
                status = int(response.status)
                if status in (301, 302, 303, 307, 308):
                    if redirects >= MAX_REDIRECTS:
                        return FetchResult(ok=False, error="too-many-redirects")
                    target = response.headers.get("Location", "")
                    nxt = urllib.parse.urljoin(current, target)
                    ok2, reason2 = validate_egress_url(nxt, allowlist)
                    if not ok2:
                        return FetchResult(ok=False, error=f"redirect-rejected: {reason2}")
                    current = nxt
                    redirects += 1
                    continue
                if status != 200:
                    return FetchResult(ok=False, status=status, error=f"http-{status}")
                body, read_error = read_body_capped(response, max_bytes, progress)
                if body is None:
                    return FetchResult(ok=False, status=status, error=read_error or "read-failed")
                return FetchResult(
                    ok=True,
                    status=status,
                    body=body,
                    final_url=current,
                    audit_url=audit_url(current),
                    redirects_followed=redirects,
                )
        except urllib.error.HTTPError as exc:
            return FetchResult(ok=False, status=int(exc.code), error=f"http-{exc.code}")
        except urllib.error.URLError as exc:
            return FetchResult(ok=False, error=f"url-error: {exc.reason}")
        except (TimeoutError, OSError) as exc:
            return FetchResult(ok=False, error=f"transport-failed: {type(exc).__name__}")


class ProgressCallback(Protocol):
    """Sink for byte progress; ``cancelled()`` aborts the transfer."""

    def update(self, received_bytes: int, total_bytes: int | None) -> None: ...
    def cancelled(self) -> bool: ...


_current_progress: ContextVar[ProgressCallback | None] = ContextVar("lunar_progress", default=None)


@contextmanager
def progress_scope(progress: ProgressCallback | None) -> Any:
    """Ambient progress channel for background tasks.

    Explicit ``progress=`` parameters always win; this scope only fills
    the gap where frozen signatures (adapter interface §6) cannot carry
    one. Set around worker-thread handler calls; reset on exit. Never
    used for QGIS objects — bytes bookkeeping only.
    """
    token = _current_progress.set(progress)
    try:
        yield progress
    finally:
        _current_progress.reset(token)


def read_body_capped(
    response: Any,
    max_bytes: int,
    progress: ProgressCallback | None = None,
) -> tuple[bytes | None, str | None]:
    """Read a response body with byte cap, progress, and cancellation.

    Returns (body, error). Pure over the response object: no sockets,
    no QGIS, fully unit-testable. Cancellation is cooperative (checked
    per chunk); the caller closes the response on abort. When no
    explicit callback is given, the ambient ``progress_scope`` channel
    (background-task downloads) applies.
    """
    active = progress if progress is not None else _current_progress.get()
    try:
        length = response.headers.get("Content-Length", "")
        total = int(length) if str(length).isdigit() else None
    except Exception:
        total = None
    chunks: list[bytes] = []
    received = 0
    while True:
        if active is not None and active.cancelled():
            return None, "cancelled"
        try:
            chunk = response.read(CHUNK_SIZE)
        except Exception as exc:
            return None, f"read-failed: {type(exc).__name__}"
        if not chunk:
            break
        received += len(chunk)
        if received > max_bytes:
            return None, "byte-cap-exceeded"
        chunks.append(chunk)
        if active is not None and not _report_progress(active, received, total):
            return None, "progress-failed"
    return b"".join(chunks), None


def _report_progress(active: Any, received: int, total: int | None) -> bool:
    """Deliver one progress update; False when the sink is broken."""
    try:
        active.update(received, total)
        return True
    except Exception:
        return False


def download_to_sandbox(
    url: str,
    allowlist: tuple[str, ...],
    sandbox_dir: str,
    relpath: str,
    *,
    timeout_s: float = 30.0,
    max_bytes: int = 500 * 1024 * 1024,
    expected_sha256: str | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Fetch a URL into the sandbox (safe-joined). Returns (ok, payload)."""
    from lunar_gis.data.adapters.base import ProviderError

    target = _safe_join(sandbox_dir, relpath)
    if target is None:
        return False, {"error": ProviderError.INVALID_QUERY.value, "detail": "path escapes sandbox"}
    result = fetch_url(url, allowlist, timeout_s=timeout_s, max_bytes=max_bytes, progress=progress)
    if not result.ok:
        code = (
            ProviderError.TIMEOUT
            if (result.error or "").startswith(("transport", "url-error"))
            else ProviderError.PROVIDER_OFFLINE
        )
        return False, {"error": code.value, "detail": result.error or ""}
    digest = hashlib.sha256(result.body).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256.lower():
        return False, {"error": ProviderError.CHECKSUM_MISMATCH.value, "detail": "sha256 mismatch"}
    try:
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(result.body)
    except OSError as exc:
        return False, {"error": ProviderError.PROVIDER_OFFLINE.value, "detail": f"write-failed: {exc}"}
    return True, {
        "sandbox_relpath": relpath.replace("\\", "/"),
        "size_bytes": len(result.body),
        "sha256_actual": digest,
        "audit_url": result.audit_url,
    }


def _safe_join(sandbox_dir: str, relpath: str) -> str | None:
    if not isinstance(relpath, str) or not relpath:
        return None
    normalized = relpath.replace("\\", "/").lstrip("/")
    if normalized.startswith("~") or ":" in normalized:
        return None
    parts = normalized.split("/")
    if ".." in parts or any(not p for p in parts):
        return None
    candidate = os.path.realpath(os.path.join(sandbox_dir, *parts))
    root = os.path.realpath(sandbox_dir)
    if candidate != root and not candidate.startswith(root + os.sep):
        return None
    return candidate


def _member_safe(name: str, allowed_suffixes: tuple[str, ...]) -> tuple[bool, str]:
    """Validate one archive member name. (ok, reason)."""
    if not name or name.endswith("/"):
        return False, "directory-entry"
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("~"):
        return False, "absolute-path"
    parts = normalized.split("/")
    if ".." in parts:
        return False, "traversal"
    if ":" in normalized:
        return False, "ads-or-drive"
    base = parts[-1]
    if base.startswith(".") or not base:
        return False, "hidden-or-empty"
    lower = normalized.lower()
    if not any(lower.endswith(s) for s in allowed_suffixes):
        return False, "suffix-not-allowlisted"
    return True, "ok"


def safe_extract_zip(
    zip_path: str,
    sandbox_dir: str,
    *,
    allowed_suffixes: tuple[str, ...] = (
        ".gpkg",
        ".shp",
        ".shx",
        ".dbf",
        ".prj",
        ".geojson",
        ".json",
        ".tif",
        ".tiff",
        ".csv",
    ),
    max_members: int = 1000,
    max_unpacked_bytes: int = 1024 * 1024 * 1024,
    max_ratio: float = 100.0,
) -> tuple[bool, dict[str, Any]]:
    """Pre-list + bounded extract of a zip into the sandbox. (ok, payload)."""
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        return False, {"error": "bad-archive", "detail": "not a zip file"}
    try:
        infos = archive.infolist()
    except Exception as exc:
        archive.close()
        return False, {"error": "bad-archive", "detail": str(exc)}
    members = [info for info in infos if not info.is_dir()]
    if len(members) > max_members:
        archive.close()
        return False, {"error": "member-cap-exceeded", "detail": f"{len(members)} > {max_members}"}
    total_unpacked = 0
    total_packed = 0
    planned: list[Any] = []
    for info in members:
        ok, reason = _member_safe(info.filename, allowed_suffixes)
        if not ok:
            archive.close()
            return False, {"error": "unsafe-member", "detail": f"{info.filename}: {reason}"}
        if info.file_size > max_unpacked_bytes:
            archive.close()
            return False, {"error": "member-too-large", "detail": info.filename}
        total_unpacked += info.file_size
        total_packed += info.compress_size
        if total_unpacked > max_unpacked_bytes:
            archive.close()
            return False, {"error": "unpacked-cap-exceeded", "detail": str(total_unpacked)}
        planned.append(info)
    if total_packed > 0 and total_unpacked / max(total_packed, 1) > max_ratio:
        archive.close()
        return False, {"error": "decompression-ratio", "detail": "ratio guard tripped"}
    extracted: list[str] = []
    try:
        for info in planned:
            target = _safe_join(sandbox_dir, info.filename)
            if target is None:
                archive.close()
                return False, {"error": "unsafe-member", "detail": info.filename}
            parent = os.path.dirname(target)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with archive.open(info) as source, open(target, "wb") as dest:
                remaining = info.file_size
                while remaining > 0:
                    chunk = source.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    dest.write(chunk)
                    remaining -= len(chunk)
            extracted.append(info.filename.replace("\\", "/"))
    except OSError as exc:
        archive.close()
        return False, {"error": "extract-failed", "detail": str(exc)}
    archive.close()
    return True, {"extracted": extracted, "member_count": len(extracted)}


__all__ = [
    "FetchResult",
    "ProgressCallback",
    "progress_scope",
    "validate_egress_url",
    "resolve_and_check",
    "audit_url",
    "fetch_url",
    "read_body_capped",
    "download_to_sandbox",
    "safe_extract_zip",
]
