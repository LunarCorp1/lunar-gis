"""M7 deterministic cartography rules (QGIS-free).

The LLM may propose a cartographic *intention*; this engine applies
deterministic rules. No AI-generated styling, no gradients-everywhere,
no color-only meaning, no inaccessible palettes.

Accessibility rules (frozen):
- Okabe-Ito palette (colorblind-safe, print-safe) in fixed order
- categorized renderers pair every color with a text label
- graduated renderers label every class with its numeric range
- text is near-black on white (contrast), minimum sizes enforced
- symbols vary by shape/size as well as color where the rule demands

Classification breaks are deterministic statistics over value lists
(not GIS math): equal-interval and quantile with fixed tie behavior.
QGIS renderers are built in ``layout_qgis`` (QGIS-bound).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

CARTO_MODEL_VERSION = "1.0"

# Okabe-Ito (colorblind-safe) in a fixed, tested order. First entry is
# the single-symbol default (vermillion-free, dark enough on white).
OKABE_ITO: tuple[str, ...] = (
    "#0072B2",  # blue
    "#E69F00",  # orange
    "#009E73",  # bluish green
    "#CC79A7",  # reddish purple
    "#56B4E9",  # sky blue
    "#D55E00",  # vermillion
    "#F0E442",  # yellow
    "#000000",  # black
)

TEXT_COLOR = "#1a1a1a"
BACKGROUND_COLOR = "#ffffff"
MIN_LABEL_SIZE_PT = 8
MIN_TITLE_SIZE_PT = 14


class ClassificationMethod(str, Enum):
    SINGLE_SYMBOL = "single-symbol"
    CATEGORIZED = "categorized"
    EQUAL_INTERVAL = "equal-interval"
    QUANTILE = "quantile"


class GeometryFamily(str, Enum):
    POINT = "Point"
    LINE = "LineString"
    POLYGON = "Polygon"
    RASTER = "Raster"


@dataclass(frozen=True)
class StyleRule:
    """Deterministic style declaration (renderer built QGIS-side)."""

    geometry: GeometryFamily
    method: ClassificationMethod = ClassificationMethod.SINGLE_SYMBOL
    palette: tuple[str, ...] = OKABE_ITO
    classes: int = 5
    field: str | None = None
    label_field: str | None = None
    opacity: float = 1.0
    line_width_mm: float = 0.5
    marker_size_mm: float = 3.0

    def __post_init__(self) -> None:
        if not 2 <= self.classes <= 9:
            raise ValueError("classes must be in [2, 9]")
        if not 0.0 < self.opacity <= 1.0:
            raise ValueError("opacity must be in (0, 1]")
        if self.method != ClassificationMethod.SINGLE_SYMBOL and not self.field:
            raise ValueError(f"{self.method.value} requires a field")


def compute_breaks(values: list[float], method: ClassificationMethod, classes: int) -> list[float]:
    """Deterministic class breaks over finite values (sorted, deduped).

    Equal-interval: min + k*(max-min)/classes. Quantile: value at
    rank positions with lower-median tie behavior. Returns the upper
    bound of each class (length == classes).
    """
    finite = sorted(v for v in values if isinstance(v, (int, float)) and v == v)
    if not finite:
        raise ValueError("no finite values to classify")
    if not 2 <= classes <= 9:
        raise ValueError("classes must be in [2, 9]")
    lo, hi = finite[0], finite[-1]
    if lo == hi:
        return [float(hi)] * classes
    if method == ClassificationMethod.EQUAL_INTERVAL:
        width = (hi - lo) / classes
        return [lo + width * (k + 1) for k in range(classes)]
    if method == ClassificationMethod.QUANTILE:
        n = len(finite)
        breaks: list[float] = []
        for k in range(1, classes + 1):
            rank = min(n - 1, (k * n) // classes)
            breaks.append(float(finite[rank]))
        # enforce strict increase (ties collapse upward deterministically)
        for i in range(1, len(breaks)):
            if breaks[i] <= breaks[i - 1]:
                breaks[i] = float(breaks[i - 1]) + 1e-9
        return breaks
    raise ValueError(f"breaks not defined for method {method.value}")


def default_style_for_geometry(geometry: str) -> StyleRule:
    """Deterministic default rule per geometry family."""
    family = GeometryFamily(geometry) if geometry in {g.value for g in GeometryFamily} else GeometryFamily.POINT
    return StyleRule(geometry=family)


def palette_for_classes(count: int) -> tuple[str, ...]:
    """First N Okabe-Ito colors (fixed order, deterministic)."""
    if not 1 <= count <= len(OKABE_ITO):
        raise ValueError(f"count must be in [1, {len(OKABE_ITO)}]")
    return OKABE_ITO[:count]


def validate_style_rule(rule: dict[str, Any]) -> list[str]:
    """Validate a style rule mapping. Empty = valid."""
    errors: list[str] = []
    if not isinstance(rule, dict):
        return ["rule must be an object"]
    geometry = rule.get("geometry", "Point")
    if geometry not in {g.value for g in GeometryFamily}:
        errors.append(f"geometry: unsupported {geometry!r}")
    method = rule.get("method", "single-symbol")
    if method not in {m.value for m in ClassificationMethod}:
        errors.append(f"method: unsupported {method!r}")
    classes = rule.get("classes", 5)
    if not isinstance(classes, int) or not 2 <= classes <= 9:
        errors.append("classes: must be an integer in [2, 9]")
    if method != "single-symbol" and not rule.get("field"):
        errors.append(f"field: required for method {method}")
    opacity = rule.get("opacity", 1.0)
    if not isinstance(opacity, (int, float)) or not 0.0 < opacity <= 1.0:
        errors.append("opacity: must be in (0, 1]")
    return errors


__all__ = [
    "CARTO_MODEL_VERSION",
    "OKABE_ITO",
    "TEXT_COLOR",
    "BACKGROUND_COLOR",
    "ClassificationMethod",
    "GeometryFamily",
    "StyleRule",
    "compute_breaks",
    "default_style_for_geometry",
    "palette_for_classes",
    "validate_style_rule",
]
