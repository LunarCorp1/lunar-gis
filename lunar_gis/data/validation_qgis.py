"""M4-T03 QGIS-authoritative local validation.

Implements the frozen §7 validation order for local/project datasets:
allowlist → integrity → parseability → emptiness → schema → CRS →
geometry validity → extent/coverage, first failure wins. QGIS/PyQGIS/GDAL
is the GIS authority (AGENTS.md:1); this module orchestrates checks and
records evidence but reimplements no CRS math, geometry predicates, or
format parsing in pure Python.

Boundary (M4-T01 §§1, 7, 9, 11):
- duck-typed ``layer``/``project`` arguments (no top-level ``import qgis``;
  QGIS classes enter only via function-level deferred imports with
  ImportError → fail-closed INVALID, so this module stays importable and
  its import guard testable without a QGIS runtime)
- MUST run on the main/GUI thread (QGIS object lifetime and SIP wrappers
  are not thread-safe)
- probe layers are constructed but never added to the project; the project
  is never mutated
- local files only: suffix + magic-byte allowlist gate first; no URLs, no
  network, no archives extraction, no subprocess/eval/exec/pickle
- file paths: exact given path only (resolved + isfile); when a
  ``sandbox_root`` is supplied, safe-join enforcement keeps writes/reads
  inside it (M4-T01 §9; future governed-tool seam)

QGIS 4 API pins: QgsVectorLayer/QgsRasterLayer open + isValid,
crs.isValid/authid, QgsGeometry.isGeosValid/validateGeometry over
getFeatures (feature-id-ordered head sample, no RNG), layer.extent with
finite guard, QgsCoordinateTransform.transformBoundingBox (densified) for
cross-CRS coverage, feature presence via filterRect request.

Public API:
- validate_project_layer(record, layer, requirement=None, project=None,
  snapshot=None) -> ValidationReport
- validate_local_file(path, requirement=None, sandbox_root=None)
  -> ValidationReport
- validate_join_key(layer_a, layer_b, key, sample_cap=...) -> JoinKeyReport
"""

from __future__ import annotations

import math
import os
from typing import Any, Sequence

from lunar_gis.data.contracts import (
    VALIDATION_MODEL_VERSION,
    JoinKeyReport,
    LayerExtent,
    LayerInventory,
    ValidationCheck,
    ValidationReport,
    ValidationVerdict,
    ValueState,
    canonicalize_geometry,
    evaluate_join_values,
    minimize_path,
    normalize_field_type,
)

# Frozen suffix allowlist, M4-T01 §7 check 1. Executables/scripts rejected
# outright (never best-effort parsed).
SUFFIX_ALLOWLIST: frozenset[str] = frozenset(
    {".gpkg", ".shp", ".geojson", ".json", ".tif", ".tiff", ".vrt", ".csv", ".zip"}
)
REJECT_SUFFIXES: frozenset[str] = frozenset(
    {".exe", ".dll", ".so", ".dylib", ".py", ".pyc", ".bat", ".ps1", ".sh", ".js"}
)

# Frozen magic-byte table: magic prefix → accepted suffixes. Text formats
# sniffed separately (UTF-8 + leading structural byte).
MAGIC_TABLE: tuple[tuple[bytes, frozenset[str]], ...] = (
    (b"SQLite format 3\x00", frozenset({".gpkg"})),
    (b"\x00\x00\x27\x0a", frozenset({".shp"})),
    (b"II*\x00", frozenset({".tif", ".tiff"})),
    (b"MM\x00*", frozenset({".tif", ".tiff"})),
    (b"PK\x03\x04", frozenset({".zip", ".gpkg"})),
)

VECTOR_SUFFIXES: frozenset[str] = frozenset({".gpkg", ".shp", ".geojson", ".json", ".csv", ".zip"})
RASTER_SUFFIXES: frozenset[str] = frozenset({".tif", ".tiff", ".vrt"})

# Implementation config (non-normative) per §16.
VALIDITY_SCAN_CAP = 1000
JOIN_SCAN_CAP = 1000
MAGIC_PROBE_BYTES = 4096


def _qgis_core() -> Any | None:
    """Deferred qgis.core import: module or None when QGIS is absent."""
    try:
        from qgis.core import (  # noqa: F401 — deferred, absence-tolerant
            QgsCoordinateReferenceSystem,
            QgsCoordinateTransform,
            QgsProject,
            QgsRasterLayer,
            QgsRectangle,
            QgsVectorLayer,
        )

        import qgis.core as core

        return core
    except ImportError:
        return None


def _check(name: str, passed: bool, detail: str, skipped: bool = False) -> ValidationCheck:
    return ValidationCheck(name=name, passed=passed, skipped=skipped, detail=detail)


def _qgis_unavailable_report(
    subject_kind: str, subject_ref: str, requirement_name: str | None, snapshot_id: str | None
) -> ValidationReport:
    """Fail-closed report when the QGIS runtime is absent (never an exception)."""
    return ValidationReport(
        subject_kind=subject_kind,
        subject_ref=subject_ref,
        requirement_name=requirement_name,
        snapshot_id=snapshot_id,
        verdict=ValidationVerdict.INVALID,
        checks=(_check("parseability", False, "qgis-runtime-unavailable"),),
        crs_authid=None,
        crs_known=False,
        geometry_canonical="Unknown",
        field_list=(),
        extent=None,
        fields_state=ValueState.UNAVAILABLE,
        feature_count=None,
        feature_count_state=ValueState.UNKNOWN,
        validity="UNCHECKED",
        validity_sample=None,
        coverage_met=None,
        coverage_method=None,
        has_time=None,
        warnings=("qgis-runtime-unavailable",),
        validation_version=VALIDATION_MODEL_VERSION,
    )


def check_suffix(path: str) -> tuple[bool, str]:
    """Suffix allowlist gate (§7 check 1, filename part only)."""
    lower = path.lower()
    for suffix in REJECT_SUFFIXES:
        if lower.endswith(suffix):
            return False, f"rejected suffix {suffix}"
    for suffix in SUFFIX_ALLOWLIST:
        if lower.endswith(suffix):
            return True, f"allowed suffix {suffix}"
    return False, "suffix not in allowlist"


def check_magic(path: str) -> tuple[bool, str]:
    """Magic-byte pre-check for a local file (no parsing)."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(MAGIC_PROBE_BYTES)
    except OSError as exc:
        return False, f"unreadable: {exc.strerror or exc}"
    if not head:
        return False, "empty file"
    lower_path = path.lower()
    for magic, suffixes in MAGIC_TABLE:
        if head.startswith(magic):
            if any(lower_path.endswith(s) for s in suffixes):
                return True, "magic matches suffix"
            return False, "magic/suffix mismatch"
    stripped = head.lstrip()
    if stripped.startswith((b"{", b"<")):
        return True, "text payload (json/xml)"
    if lower_path.endswith(".csv"):
        try:
            text = head.decode("utf-8")
        except UnicodeDecodeError:
            return False, "csv not utf-8 text"
        if "," in text or "\n" in text:
            return True, "text payload (csv)"
        return False, "csv without delimiter"
    return False, "unrecognized magic"


def _safe_join(sandbox_root: str, relpath: str) -> str | None:
    """Resolve relpath inside sandbox_root; None on traversal/absolute."""
    if not isinstance(relpath, str) or not relpath:
        return None
    normalized = relpath.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("~"):
        return None
    if ".." in normalized.split("/"):
        return None
    if ":" in normalized:  # ADS streams / drive specs / UNC
        return None
    candidate = os.path.realpath(os.path.join(sandbox_root, *normalized.split("/")))
    root = os.path.realpath(sandbox_root)
    if candidate != root and not candidate.startswith(root + os.sep):
        return None
    return candidate


def _resolve_local_path(path: str, sandbox_root: str | None) -> tuple[str | None, str]:
    """Resolve a local path: sandbox-joined when a root is given, else exact.

    Returns (resolved_path | None, reason). Never globs; opens exactly the
    given path (symlinks resolved via realpath for the isfile decision).
    """
    if not isinstance(path, str) or not path:
        return None, "empty path"
    if sandbox_root is not None:
        joined = _safe_join(sandbox_root, path)
        if joined is None:
            return None, "path escapes sandbox"
        resolved = joined
    else:
        resolved = os.path.realpath(path)
    if os.path.isdir(resolved):
        return None, "path is a directory"
    if not os.path.isfile(resolved):
        return None, "not a file"
    return resolved, "ok"


def _read_crs_info(layer: Any) -> tuple[str | None, bool]:
    try:
        crs = layer.crs()
    except Exception:
        return None, False
    try:
        valid = bool(crs.isValid())
    except Exception:
        valid = False
    try:
        authid = crs.authid()
    except Exception:
        return None, False
    if not authid:
        return None, False
    return str(authid), valid


def _read_field_list(layer: Any) -> tuple[tuple[tuple[str, str], ...] | None, ValueState]:
    if not hasattr(layer, "fields"):
        return None, ValueState.UNAVAILABLE
    try:
        fields = layer.fields()
        names = list(fields.names())
    except Exception:
        return None, ValueState.UNAVAILABLE
    result: list[tuple[str, str]] = []
    for name in names:
        try:
            field = fields.field(name)
            type_name = str(field.typeName()) if field is not None else "Unknown"
        except Exception:
            type_name = "Unknown"
        result.append((str(name), normalize_field_type(type_name)))
    return tuple(result), ValueState.KNOWN


def _read_extent(layer: Any, crs_authid: str | None) -> tuple[LayerExtent | None, ValueState]:
    if not hasattr(layer, "extent"):
        return None, ValueState.UNAVAILABLE
    try:
        box = layer.extent()
        values = (float(box.xMinimum()), float(box.yMinimum()), float(box.xMaximum()), float(box.yMaximum()))
    except Exception:
        return None, ValueState.UNAVAILABLE
    if not all(math.isfinite(v) for v in values) or crs_authid is None:
        return None, ValueState.UNAVAILABLE
    xmin, ymin, xmax, ymax = values
    return LayerExtent(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax, crs_authid=crs_authid), ValueState.KNOWN


def _read_feature_count(layer: Any) -> tuple[int | None, ValueState]:
    if not hasattr(layer, "featureCount"):
        return None, ValueState.UNAVAILABLE
    try:
        count = int(layer.featureCount())
    except (TypeError, ValueError, RuntimeError, AttributeError):
        return None, ValueState.UNAVAILABLE
    if count == -1:
        return None, ValueState.UNKNOWN
    if count < -1:
        return None, ValueState.UNAVAILABLE
    return count, ValueState.KNOWN


def _sample_validity(
    layer: Any, feature_count: int | None, cap: int | None = None
) -> tuple[str, tuple[int, int | None] | None, bool]:
    """Deterministic head-sample validity: (validity, sample|None, all_valid).

    Iterates getFeatures(), sorts collected ids (no RNG), evaluates the
    head up to cap with isGeosValid (null geometry counts invalid).
    Returns UNCHECKED when iteration is impossible. The cap resolves at
    call time (module constant default) so tests may bound the scan.
    """
    limit = cap if cap is not None else VALIDITY_SCAN_CAP
    if not hasattr(layer, "getFeatures"):
        return "UNCHECKED", None, True
    try:
        iterator = layer.getFeatures()
    except Exception:
        return "UNCHECKED", None, True
    collected: list[tuple[int, bool]] = []
    overflow = False
    try:
        for feature in iterator:
            try:
                fid = int(feature.id())
            except Exception:
                fid = len(collected)
            try:
                geometry = feature.geometry()
                if geometry is None or geometry.isNull():
                    valid = False
                else:
                    valid = bool(geometry.isGeosValid())
            except Exception:
                valid = False
            collected.append((fid, valid))
            if len(collected) > limit:
                overflow = True
                break
    except Exception:
        return "UNCHECKED", None, True
    if not collected:
        return "UNCHECKED", None, True
    collected.sort(key=lambda item: item[0])
    head = collected[:limit]
    complete = not overflow and feature_count is not None and len(collected) == feature_count
    all_valid = all(valid for _, valid in head)
    return ("FULL" if complete else "PARTIAL", (len(head), feature_count), all_valid)


def _transformed_containment(
    layer_extent: LayerExtent,
    requirement_extent: Any,
    layer_crs_authid: str,
) -> tuple[bool | None, str]:
    """Normative coverage: requirement bbox vs layer extent via QGIS CRS math.

    Transforms the layer extent into the requirement CRS with densified
    transformBoundingBox (QGIS authority — never naive corner math, never
    degrees²-vs-m²), then tests containment. Returns (met|None, method).
    None = transform failed or QGIS absent (deferred, never guessed).
    """
    core = _qgis_core()
    if core is None:
        return None, "qgis-unavailable"
    try:
        source_crs = core.QgsCoordinateReferenceSystem(layer_crs_authid)
        dest_crs = core.QgsCoordinateReferenceSystem(requirement_extent.crs_authid)
        transform = core.QgsCoordinateTransform(source_crs, dest_crs, core.QgsProject.instance())
        box = core.QgsRectangle(layer_extent.xmin, layer_extent.ymin, layer_extent.xmax, layer_extent.ymax)
        moved = transform.transformBoundingBox(box)
        met = (
            moved.xMinimum() <= requirement_extent.xmin
            and moved.yMinimum() <= requirement_extent.ymin
            and moved.xMaximum() >= requirement_extent.xmax
            and moved.yMaximum() >= requirement_extent.ymax
        )
        return bool(met), "transformed-bbox-containment"
    except Exception as exc:
        return None, f"transform-failed: {type(exc).__name__}"


def _feature_presence(layer: Any, requirement_extent: Any, layer_crs_authid: str) -> tuple[bool | None, str]:
    """True data-presence probe: count features intersecting the requirement.

    Transforms the requirement bbox into the layer CRS (densified QGIS
    transform) and counts intersecting features via filterRect (no geometry
    fetched). Capped scan; None when the transform or request fails.
    """
    core = _qgis_core()
    if core is None or not hasattr(layer, "getFeatures"):
        return None, "qgis-unavailable"
    try:
        source_crs = core.QgsCoordinateReferenceSystem(requirement_extent.crs_authid)
        dest_crs = core.QgsCoordinateReferenceSystem(layer_crs_authid)
        transform = core.QgsCoordinateTransform(source_crs, dest_crs, core.QgsProject.instance())
        box = core.QgsRectangle(
            requirement_extent.xmin,
            requirement_extent.ymin,
            requirement_extent.xmax,
            requirement_extent.ymax,
        )
        in_layer_crs = transform.transformBoundingBox(box)
        request = core.QgsFeatureRequest().setFilterRect(in_layer_crs)
        request.setFlags(core.QgsFeatureRequest.NoGeometry)
        count = 0
        for _ in layer.getFeatures(request):
            count += 1
            if count > 0:
                break
        return (count > 0), f"feature-presence(count>0={count > 0})"
    except Exception as exc:
        return None, f"presence-probe-failed: {type(exc).__name__}"


def _validate_open_layer(
    layer: Any,
    *,
    subject_kind: str,
    subject_ref: str,
    requirement: Any | None,
    snapshot_id: str | None,
    geometry_override: str | None = None,
    extra_warnings: Sequence[str] = (),
) -> ValidationReport:
    """Run the frozen §7 check order over an open layer. Main thread only."""
    """Run the frozen §7 check order over an open layer. Main thread only."""
    checks: list[ValidationCheck] = []
    warnings: list[str] = list(extra_warnings)

    def fail(name: str, detail: str) -> ValidationReport:
        checks.append(_check(name, False, detail))
        return _finish(ValidationVerdict.INVALID)

    def _finish(verdict: ValidationVerdict) -> ValidationReport:
        return ValidationReport(
            subject_kind=subject_kind,
            subject_ref=subject_ref,
            requirement_name=requirement.name if requirement is not None else None,
            snapshot_id=snapshot_id,
            verdict=verdict,
            checks=tuple(checks),
            crs_authid=_crs_authid,
            crs_known=_crs_known,
            geometry_canonical=_canonical,
            field_list=_fields if _fields is not None else (),
            extent=_extent,
            fields_state=_fields_state,
            feature_count=_count,
            feature_count_state=_count_state,
            validity=_validity,
            validity_sample=_sample,
            coverage_met=_coverage_met,
            coverage_method=_coverage_method,
            has_time=_has_time,
            warnings=tuple(warnings),
        )

    # 1-3. allowlist/integrity/parseability are established by the caller
    # (suffix+magic for files; snapshot presence for project layers).
    # Parseability: the layer opened.
    try:
        opened = bool(layer.isValid())
    except Exception:
        opened = False
    if not opened:
        checks.append(_check("parseability", False, "layer failed to open"))
        _crs_authid, _crs_known, _canonical = None, False, "Unknown"
        _fields, _fields_state = None, ValueState.UNAVAILABLE
        _extent = None
        _count, _count_state = None, ValueState.UNKNOWN
        _validity, _sample = "UNCHECKED", None
        _coverage_met, _coverage_method = None, None
        _has_time = None
        return _finish(ValidationVerdict.INVALID)
    checks.append(_check("parseability", True, "layer opened"))

    _crs_authid, _crs_known = _read_crs_info(layer)
    if geometry_override is not None:
        _canonical = geometry_override
    else:
        try:
            opaque = str(layer.geometryType()) if hasattr(layer, "geometryType") else None
        except Exception:
            opaque = None
        _canonical = canonicalize_geometry(opaque)
    _fields_raw, _fields_state = _read_field_list(layer)
    _fields = _fields_raw
    _count, _count_state = _read_feature_count(layer)

    # 4. Emptiness short-circuit (remaining checks recorded skipped-empty).
    if _count_state == ValueState.KNOWN and _count == 0:
        checks.append(_check("emptiness", True, "zero features known"))
        for name in ("schema", "crs", "geometry", "coverage"):
            checks.append(_check(name, False, "skipped-empty", skipped=True))
        _extent = None
        _validity, _sample = "UNCHECKED", None
        _coverage_met, _coverage_method = None, None
        try:
            _has_time = _read_has_time(layer)
        except Exception:
            _has_time = None
        return _finish(ValidationVerdict.EMPTY)
    checks.append(_check("emptiness", True, f"non-empty (count={_count})"))

    # 5. Schema present (constraint matching is satisfy() scope).
    checks.append(
        _check(
            "schema",
            True,
            f"{len(_fields) if _fields else 0} fields read"
            if _fields_state == ValueState.KNOWN
            else "fields unavailable",
        )
    )

    # 6. CRS.
    checks.append(
        _check(
            "crs",
            True,
            f"crs={_crs_authid}" if _crs_known else "crs unknown (aspatial-only)",
        )
    )

    # 7. Geometry validity: deterministic head sample (not layer isValid).
    _validity, _sample, _all_valid = _sample_validity(layer, _count if _count_state == ValueState.KNOWN else None)
    if not _all_valid:
        checks.append(_check("geometry", False, "invalid geometries in sample"))
        _extent, _coverage_met, _coverage_method = None, None, None
        _has_time = _read_has_time(layer)
        return _finish(ValidationVerdict.INVALID)
    if _validity == "PARTIAL" and _sample is not None:
        sampled, total = _sample
        checks.append(_check("geometry", True, f"sample valid PARTIAL(sampled {sampled}/{total})"))
        warnings.append(f"validity-partial(sampled {sampled}/{total})")
    else:
        checks.append(_check("geometry", True, f"validity {_validity}"))

    # 8. Extent/coverage: re-query deferred extent explicitly, then
    # normative transformed containment + feature presence.
    _extent, _extent_state = _read_extent(layer, _crs_authid)
    if _extent is None:
        checks.append(_check("coverage", False, "extent unavailable"))
        _coverage_met, _coverage_method = None, "extent-unavailable"
        _has_time = _read_has_time(layer)
        return _finish(ValidationVerdict.INVALID)
    _coverage_met, _coverage_method = None, None
    if requirement is not None and requirement.extent is not None:
        if not _crs_known or _crs_authid is None:
            checks.append(_check("coverage", False, "crs unknown for coverage"))
            _coverage_met, _coverage_method = None, "crs-unknown"
        else:
            met, method = _transformed_containment(_extent, requirement.extent, _crs_authid)
            _coverage_method = method
            if met is None:
                checks.append(_check("coverage", False, f"coverage deferred ({method})"))
                _coverage_met = None
            elif not met:
                checks.append(_check("coverage", False, "transformed extent does not contain requirement"))
                _coverage_met = False
            else:
                present, presence_method = _feature_presence(layer, requirement.extent, _crs_authid)
                if present is None:
                    checks.append(_check("coverage", True, f"bbox contained; presence {presence_method}"))
                    _coverage_met = True
                    warnings.append("coverage-bbox-only")
                elif not present:
                    checks.append(_check("coverage", False, "no features intersect requirement"))
                    _coverage_met = False
                else:
                    checks.append(_check("coverage", True, "bbox contained + features present"))
                    _coverage_met = True
                    _coverage_method = f"{method}+feature-presence"
    else:
        checks.append(_check("coverage", True, "no coverage constraint"))
        _coverage_met = True
        _coverage_method = "no-constraint"
    warnings.append("coverage-bbox-limitation:holes-nodata-need-feature-checks")
    _has_time = _read_has_time(layer)
    return _finish(ValidationVerdict.VALID)


def _read_has_time(layer: Any) -> bool | None:
    if not hasattr(layer, "temporalProperties"):
        return None
    try:
        props = layer.temporalProperties()
    except Exception:
        return None
    if props is None:
        return None
    try:
        return bool(props.isActive())
    except Exception:
        return None


def validate_project_layer(
    record: Any,
    layer: Any,
    requirement: Any | None = None,
    *,
    project: Any | None = None,
    snapshot: LayerInventory | None = None,
) -> ValidationReport:
    """Validate a project layer against an optional requirement. Main thread.

    Staleness (fail-closed): when both ``project`` and ``snapshot`` are
    given and the project is dirty or the layer count changed since the
    snapshot, validation refuses with an INVALID snapshot-freshness check
    (§1.3: re-snapshot before validation). Without a snapshot the check is
    recorded with a snapshot-unverified warning instead of failing.
    The live ``layer`` is never added to the project; the project is never
    mutated.
    """
    subject_ref = record.layer_id if hasattr(record, "layer_id") else ""
    snapshot_id = snapshot.snapshot_id if snapshot is not None else None
    if project is not None and snapshot is not None:
        try:
            dirty = bool(project.isDirty()) if hasattr(project, "isDirty") else False
            count = len(list(project.mapLayers().values()))
        except Exception:
            dirty, count = False, -1
        if dirty or (count >= 0 and count != snapshot.total_count):
            return ValidationReport(
                subject_kind="layer-ref",
                subject_ref=subject_ref,
                requirement_name=requirement.name if requirement is not None else None,
                snapshot_id=snapshot_id,
                verdict=ValidationVerdict.INVALID,
                checks=(_check("snapshot-freshness", False, "snapshot stale: re-snapshot required"),),
                crs_authid=None,
                crs_known=False,
                geometry_canonical="Unknown",
                field_list=(),
                extent=None,
                fields_state=ValueState.UNAVAILABLE,
                feature_count=None,
                feature_count_state=ValueState.UNKNOWN,
                validity="UNCHECKED",
                validity_sample=None,
                coverage_met=None,
                coverage_method=None,
                has_time=None,
                warnings=("stale-snapshot",),
            )
    if _qgis_core() is None:
        # Without QGIS only duck-typed checks can run; QGIS-powered steps
        # (CRS transform, feature presence) degrade to deferred inside the
        # pipeline. Probe construction (files) still needs the runtime.
        runtime_warnings: tuple[str, ...] = ("qgis-runtime-absent:qgis-powered-steps-deferred",)
    else:
        runtime_warnings = ()
    return _validate_open_layer(
        layer,
        subject_kind="layer-ref",
        subject_ref=subject_ref,
        requirement=requirement,
        snapshot_id=snapshot_id,
        extra_warnings=runtime_warnings,
    )


def validate_local_file(
    path: str,
    requirement: Any | None = None,
    *,
    sandbox_root: str | None = None,
) -> ValidationReport:
    """Validate a local file without adding anything to the project.

    Exactly the given path is opened (symlinks resolved for the isfile
    decision; no globbing, no traversal beyond it). With ``sandbox_root``,
    safe-join enforcement keeps the path inside it (governed-tool seam).
    Suffix + magic-byte gate first (§7 check 1); probe layer constructed
    via deferred QGIS import (absent runtime → fail-closed INVALID).
    """
    minimized = minimize_path(path) if isinstance(path, str) else ""
    resolved, reason = _resolve_local_path(path, sandbox_root)
    if resolved is None:
        return ValidationReport(
            subject_kind="file",
            subject_ref=minimized,
            requirement_name=requirement.name if requirement is not None else None,
            snapshot_id=None,
            verdict=ValidationVerdict.INVALID,
            checks=(_check("allowlist", False, reason),),
            crs_authid=None,
            crs_known=False,
            geometry_canonical="Unknown",
            field_list=(),
            extent=None,
            fields_state=ValueState.UNAVAILABLE,
            feature_count=None,
            feature_count_state=ValueState.UNKNOWN,
            validity="UNCHECKED",
            validity_sample=None,
            coverage_met=None,
            coverage_method=None,
            has_time=None,
            warnings=("path-rejected",),
        )
    ok, suffix_detail = check_suffix(resolved)
    if not ok:
        return ValidationReport(
            subject_kind="file",
            subject_ref=minimized,
            requirement_name=requirement.name if requirement is not None else None,
            snapshot_id=None,
            verdict=ValidationVerdict.INVALID,
            checks=(
                _check("allowlist", True, "path resolved"),
                _check("allowlist", False, suffix_detail),
            ),
            crs_authid=None,
            crs_known=False,
            geometry_canonical="Unknown",
            field_list=(),
            extent=None,
            fields_state=ValueState.UNAVAILABLE,
            feature_count=None,
            feature_count_state=ValueState.UNKNOWN,
            validity="UNCHECKED",
            validity_sample=None,
            coverage_met=None,
            coverage_method=None,
            has_time=None,
            warnings=("suffix-rejected",),
        )
    magic_ok, magic_detail = check_magic(resolved)
    if not magic_ok:
        return ValidationReport(
            subject_kind="file",
            subject_ref=minimized,
            requirement_name=requirement.name if requirement is not None else None,
            snapshot_id=None,
            verdict=ValidationVerdict.INVALID,
            checks=(
                _check("allowlist", True, "path resolved + suffix ok"),
                _check("integrity", False, magic_detail),
            ),
            crs_authid=None,
            crs_known=False,
            geometry_canonical="Unknown",
            field_list=(),
            extent=None,
            fields_state=ValueState.UNAVAILABLE,
            feature_count=None,
            feature_count_state=ValueState.UNKNOWN,
            validity="UNCHECKED",
            validity_sample=None,
            coverage_met=None,
            coverage_method=None,
            has_time=None,
            warnings=("magic-rejected",),
        )
    core = _qgis_core()
    if core is None:
        return _qgis_unavailable_report("file", minimized, requirement.name if requirement is not None else None, None)
    lower = resolved.lower()
    try:
        if any(lower.endswith(s) for s in RASTER_SUFFIXES):
            probe = core.QgsRasterLayer(resolved, "lunar-probe", "gdal")
            geometry_override: str | None = "Raster"
        else:
            probe = core.QgsVectorLayer(resolved, "lunar-probe", "ogr")
            geometry_override = None
    except Exception:
        return ValidationReport(
            subject_kind="file",
            subject_ref=minimized,
            requirement_name=requirement.name if requirement is not None else None,
            snapshot_id=None,
            verdict=ValidationVerdict.INVALID,
            checks=(
                _check("allowlist", True, "suffix+magic ok"),
                _check("parseability", False, "probe construction failed"),
            ),
            crs_authid=None,
            crs_known=False,
            geometry_canonical="Unknown",
            field_list=(),
            extent=None,
            fields_state=ValueState.UNAVAILABLE,
            feature_count=None,
            feature_count_state=ValueState.UNKNOWN,
            validity="UNCHECKED",
            validity_sample=None,
            coverage_met=None,
            coverage_method=None,
            has_time=None,
            warnings=("probe-failed",),
        )
    report = _validate_open_layer(
        probe,
        subject_kind="file",
        subject_ref=minimized,
        requirement=requirement,
        snapshot_id=None,
        geometry_override=geometry_override,
    )
    return report


def validate_join_key(layer_a: Any, layer_b: Any, key: str, sample_cap: int | None = None) -> JoinKeyReport:
    """Validate a join key over two live layers (bounded head-sample scan).

    Iterates getFeatures() on the main thread, feature-id ordered, capped;
    delegates the frozen rule to contracts.evaluate_join_values.
    layer names + redacted sources only in evidence — never row contents.
    The cap resolves at call time (module constant default).
    """
    cap = sample_cap if sample_cap is not None else JOIN_SCAN_CAP

    def collect(layer: Any) -> tuple[dict[str, str], list[Any], int, bool]:
        try:
            fields = layer.fields()
            names = list(fields.names())
        except Exception:
            return {}, [], 0, False
        field_types: dict[str, str] = {}
        for name in names:
            try:
                field = fields.field(name)
                field_types[str(name)] = str(field.typeName()) if field is not None else "Unknown"
            except Exception:
                field_types[str(name)] = "Unknown"
        values: list[Any] = []
        seen = 0
        complete = True
        try:
            gathered: list[tuple[int, Any]] = []
            for feature in layer.getFeatures():
                seen += 1
                try:
                    fid = int(feature.id())
                except Exception:
                    fid = seen
                try:
                    value = feature.attribute(key)
                except Exception:
                    value = None
                gathered.append((fid, value))
                if len(gathered) > cap:
                    complete = False
                    break
            gathered.sort(key=lambda item: item[0])
            values = [value for _, value in gathered[:cap]]
        except Exception:
            return field_types, [], seen, False
        try:
            total = int(layer.featureCount())
            if total >= 0 and seen >= total:
                complete = True
            elif total < 0:
                complete = False
        except Exception:
            complete = False
        return field_types, values, seen, complete

    left_fields, left_values, _, left_complete = collect(layer_a)
    right_fields, right_values, _, right_complete = collect(layer_b)
    return evaluate_join_values(
        key, left_fields, right_fields, left_values, right_values, left_complete and right_complete
    )


__all__ = [
    "SUFFIX_ALLOWLIST",
    "REJECT_SUFFIXES",
    "VALIDITY_SCAN_CAP",
    "JOIN_SCAN_CAP",
    "check_suffix",
    "check_magic",
    "validate_project_layer",
    "validate_local_file",
    "validate_join_key",
]
