"""QGIS Processing provider for Lunar GIS.

Registers deterministic GIS analysis algorithms under the "lunar_gis" namespace.
Provider is purely declarative — algorithms are registered at import time
and executed through QGIS Processing.

Public API:
  - LunarGISProvider: QgsProcessingProvider subclass
"""

from __future__ import annotations

from typing import Any

from qgis.core import QgsProcessingProvider

from lunar_gis.processing.ahp_algorithm import AHPAlgorithm
from lunar_gis.processing.sensitivity_algorithm import AHPSensitivityAlgorithm
from lunar_gis.processing.transform_algorithms import TRANSFORM_ALGORITHMS


class LunarGISProvider(QgsProcessingProvider):
    """Processing provider for Lunar GIS deterministic analysis algorithms."""

    def loadAlgorithms(self) -> None:
        self.addAlgorithm(AHPAlgorithm())
        self.addAlgorithm(AHPSensitivityAlgorithm())
        for algorithm_cls in TRANSFORM_ALGORITHMS:
            self.addAlgorithm(algorithm_cls())

    def id(self) -> str:  # noqa: A003
        return "lunar_gis"

    def name(self) -> str:
        return "Lunar GIS"

    def longName(self) -> str:
        return "Lunar GIS — Deterministic Analysis"

    def icon(self) -> Any:
        return super().icon()
