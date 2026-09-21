"""M8 reproducible report models (QGIS-free).

Analytical content vs presentation metadata (M3-T04 philosophy):
- ``ReportContent``: everything that determines the analysis
  (request, requirements, data, transforms, analysis, results,
  warnings, provenance, versions). Hashable, reproducible.
- ``ReportEnvelope``: presentation metadata (generated_at, generator,
  format). NEVER part of the analytical identity — timestamps must
  not break reproducibility hashes.

A report is a ``ReportModel`` (content + envelope). ``content_identity``
is sha256 over canonical analytical JSON only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

REPORT_MODEL_VERSION = "1.0"


@dataclass(frozen=True)
class ReportContent:
    """Analytical content (hashable, no timestamps)."""

    title: str
    user_request: str
    requirements: tuple[dict[str, Any], ...] = ()
    data_used: tuple[dict[str, Any], ...] = ()
    missing_data: tuple[dict[str, Any], ...] = ()
    transformations: tuple[dict[str, Any], ...] = ()
    analysis: tuple[dict[str, Any], ...] = ()
    results: tuple[dict[str, Any], ...] = ()
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    provenance: tuple[dict[str, Any], ...] = ()
    licenses: tuple[dict[str, Any], ...] = ()
    engine_versions: dict[str, str] = field(default_factory=dict)
    policy_versions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ReportEnvelope:
    """Presentation metadata (never hashed into identity)."""

    generated_at: str
    generator: str = "lunar-gis"
    generator_version: str = REPORT_MODEL_VERSION
    format: str = "html"


@dataclass(frozen=True)
class ReportModel:
    content: ReportContent
    envelope: ReportEnvelope
    report_version: str = REPORT_MODEL_VERSION


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def content_to_dict(content: ReportContent) -> dict[str, Any]:
    return {
        "title": content.title,
        "user_request": content.user_request,
        "requirements": _jsonable(content.requirements),
        "data_used": _jsonable(content.data_used),
        "missing_data": _jsonable(content.missing_data),
        "transformations": _jsonable(content.transformations),
        "analysis": _jsonable(content.analysis),
        "results": _jsonable(content.results),
        "assumptions": list(content.assumptions),
        "warnings": list(content.warnings),
        "provenance": _jsonable(content.provenance),
        "licenses": _jsonable(content.licenses),
        "engine_versions": dict(content.engine_versions),
        "policy_versions": dict(content.policy_versions),
    }


def content_canonical_json(content: ReportContent) -> str:
    return json.dumps(content_to_dict(content), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_identity(content: ReportContent) -> str:
    """sha256 over analytical content only (envelope excluded)."""
    return hashlib.sha256(content_canonical_json(content).encode("utf-8")).hexdigest()


def make_content(title: str, user_request: str, **kwargs: Any) -> ReportContent:
    if not title or not user_request:
        raise ValueError("title and user_request are required")
    return ReportContent(
        title=title,
        user_request=user_request,
        requirements=tuple(kwargs.get("requirements", ())),
        data_used=tuple(kwargs.get("data_used", ())),
        missing_data=tuple(kwargs.get("missing_data", ())),
        transformations=tuple(kwargs.get("transformations", ())),
        analysis=tuple(kwargs.get("analysis", ())),
        results=tuple(kwargs.get("results", ())),
        assumptions=tuple(kwargs.get("assumptions", ())),
        warnings=tuple(kwargs.get("warnings", ())),
        provenance=tuple(kwargs.get("provenance", ())),
        licenses=tuple(kwargs.get("licenses", ())),
        engine_versions=dict(kwargs.get("engine_versions", {})),
        policy_versions=dict(kwargs.get("policy_versions", {})),
    )


__all__ = [
    "REPORT_MODEL_VERSION",
    "ReportContent",
    "ReportEnvelope",
    "ReportModel",
    "content_to_dict",
    "content_canonical_json",
    "content_identity",
    "make_content",
]
