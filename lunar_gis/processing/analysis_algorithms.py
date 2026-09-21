"""QGIS Processing algorithms for governed GIS analysis (M6).

Thin wrappers over pinned native algorithms — no GIS math here.
Each algorithm declares explicit params, runs the native pin, and
returns memory outputs. The governed ``analysis.*`` tools execute the
same pins through ``gis_tools`` handlers.

Pins: native:buffer, native:intersection, native:dissolve,
native:zonalstatisticsfb, native:joinattributesbylocation
(pinned versions in lunar_gis.analysis.gis_tools.GIS_PINS).
"""

from __future__ import annotations

from typing import Any

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingOutputVectorLayer,
    QgsProcessingParameterDistance,
    QgsProcessingParameterEnum,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
)

from lunar_gis.analysis.gis_tools import GIS_PINS


class GisAnalysisBase(QgsProcessingAlgorithm):
    OP = ""

    def createInstance(self) -> GisAnalysisBase:
        return type(self)()

    def group(self) -> str:
        return "Analysis"

    def groupId(self) -> str:
        return "analysis"

    def _run_pinned(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        import processing  # type: ignore[import-not-found]

        alg_id, alg_version = GIS_PINS[self.OP]
        alg_params = self._alg_params(parameters, context)
        feedback.pushInfo(f"Lunar GIS {self.OP} via {alg_id}@{alg_version}")
        try:
            result = processing.run(alg_id, alg_params, context=context, feedback=feedback)
            return dict(result)
        except Exception as exc:
            raise QgsProcessingException(f"{self.OP} failed: {exc}") from exc

    def _alg_params(self, parameters: dict[str, Any], context: QgsProcessingContext) -> dict[str, Any]:
        raise NotImplementedError


class BufferAlgorithm(GisAnalysisBase):
    OP = "buffer"
    INPUT = "INPUT"
    DISTANCE = "DISTANCE"
    SEGMENTS = "SEGMENTS"
    OUTPUT = "OUTPUT"

    def name(self) -> str:
        return "gis_buffer"

    def displayName(self) -> str:
        return "Buffer Layer"

    def shortHelpString(self) -> str:
        return "Fixed-distance buffer with explicit distance and segments (native:buffer)."

    def initAlgorithm(self, config: dict[str, Any] | None = None) -> None:
        _ = config
        self.addParameter(QgsProcessingParameterVectorLayer(self.INPUT, "Input layer"))
        self.addParameter(QgsProcessingParameterDistance(self.DISTANCE, "Distance", defaultValue=100.0))
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SEGMENTS, "Segments", type=QgsProcessingParameterNumber.Integer, defaultValue=5
            )
        )
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT, "Buffered"))

    def _alg_params(self, parameters: dict[str, Any], context: QgsProcessingContext) -> dict[str, Any]:
        return {
            "INPUT": self.parameterAsVectorLayer(parameters, self.INPUT, context),
            "DISTANCE": self.parameterAsDouble(parameters, self.DISTANCE, context),
            "SEGMENTS": self.parameterAsInt(parameters, self.SEGMENTS, context),
            "DISSOLVE": False,
            "OUTPUT": "memory:",
        }

    def processAlgorithm(
        self, parameters: dict[str, Any], context: QgsProcessingContext, feedback: QgsProcessingFeedback
    ) -> dict[str, Any]:
        result = self._run_pinned(parameters, context, feedback)
        return {self.OUTPUT: result["OUTPUT"]}


class IntersectionAlgorithm(GisAnalysisBase):
    OP = "intersection"
    INPUT = "INPUT"
    OVERLAY = "OVERLAY"
    OUTPUT = "OUTPUT"

    def name(self) -> str:
        return "gis_intersection"

    def displayName(self) -> str:
        return "Intersect Layers"

    def shortHelpString(self) -> str:
        return "Geometric intersection of two layers (native:intersection)."

    def initAlgorithm(self, config: dict[str, Any] | None = None) -> None:
        _ = config
        self.addParameter(QgsProcessingParameterVectorLayer(self.INPUT, "Input layer"))
        self.addParameter(QgsProcessingParameterVectorLayer(self.OVERLAY, "Overlay layer"))
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT, "Intersection"))

    def _alg_params(self, parameters: dict[str, Any], context: QgsProcessingContext) -> dict[str, Any]:
        return {
            "INPUT": self.parameterAsVectorLayer(parameters, self.INPUT, context),
            "OVERLAY": self.parameterAsVectorLayer(parameters, self.OVERLAY, context),
            "OUTPUT": "memory:",
        }

    def processAlgorithm(
        self, parameters: dict[str, Any], context: QgsProcessingContext, feedback: QgsProcessingFeedback
    ) -> dict[str, Any]:
        result = self._run_pinned(parameters, context, feedback)
        return {self.OUTPUT: result["OUTPUT"]}


class DissolveAlgorithm(GisAnalysisBase):
    OP = "dissolve"
    INPUT = "INPUT"
    FIELD = "FIELD"
    OUTPUT = "OUTPUT"

    def name(self) -> str:
        return "gis_dissolve"

    def displayName(self) -> str:
        return "Dissolve Layer"

    def shortHelpString(self) -> str:
        return "Dissolve features, optionally grouped by a field (native:dissolve)."

    def initAlgorithm(self, config: dict[str, Any] | None = None) -> None:
        _ = config
        self.addParameter(QgsProcessingParameterVectorLayer(self.INPUT, "Input layer"))
        self.addParameter(
            QgsProcessingParameterField(
                self.FIELD, "Dissolve field", parentLayerParameterName=self.INPUT, optional=True
            )
        )
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT, "Dissolved"))

    def _alg_params(self, parameters: dict[str, Any], context: QgsProcessingContext) -> dict[str, Any]:
        fields = self.parameterAsFields(parameters, self.FIELD, context)
        return {
            "INPUT": self.parameterAsVectorLayer(parameters, self.INPUT, context),
            "FIELD": fields,
            "OUTPUT": "memory:",
        }

    def processAlgorithm(
        self, parameters: dict[str, Any], context: QgsProcessingContext, feedback: QgsProcessingFeedback
    ) -> dict[str, Any]:
        result = self._run_pinned(parameters, context, feedback)
        return {self.OUTPUT: result["OUTPUT"]}


class ZonalStatisticsAlgorithm(GisAnalysisBase):
    OP = "zonal_statistics"
    INPUT = "INPUT"
    RASTER = "RASTER"
    STATISTICS = "STATISTICS"
    OUTPUT = "OUTPUT"

    def name(self) -> str:
        return "gis_zonal_statistics"

    def displayName(self) -> str:
        return "Zonal Statistics"

    def shortHelpString(self) -> str:
        return "Raster statistics per polygon zone (native:zonalstatisticsfb)."

    def initAlgorithm(self, config: dict[str, Any] | None = None) -> None:
        _ = config
        self.addParameter(QgsProcessingParameterVectorLayer(self.INPUT, "Zone layer"))
        self.addParameter(QgsProcessingParameterRasterLayer(self.RASTER, "Raster layer"))
        self.addParameter(
            QgsProcessingParameterEnum(
                self.STATISTICS,
                "Statistics",
                options=["Count", "Sum", "Mean", "Median", "Min", "Max"],
                allowMultiple=True,
                defaultValue=[0, 1, 2],
            )
        )
        self.addParameter(
            QgsProcessingParameterString(self.OUTPUT + "_PREFIX", "Output prefix", defaultValue="z_", optional=True)
        )
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT, "Zonal statistics"))

    def _alg_params(self, parameters: dict[str, Any], context: QgsProcessingContext) -> dict[str, Any]:
        return {
            "INPUT": self.parameterAsVectorLayer(parameters, self.INPUT, context),
            "INPUT_RASTER": self.parameterAsRasterLayer(parameters, self.RASTER, context),
            "RASTER_BAND": 1,
            "STATISTICS": self.parameterAsEnums(parameters, self.STATISTICS, context),
            "OUTPUT": "memory:",
        }

    def processAlgorithm(
        self, parameters: dict[str, Any], context: QgsProcessingContext, feedback: QgsProcessingFeedback
    ) -> dict[str, Any]:
        result = self._run_pinned(parameters, context, feedback)
        return {self.OUTPUT: result["OUTPUT"]}


class SpatialJoinAlgorithm(GisAnalysisBase):
    OP = "spatial_join"
    INPUT = "INPUT"
    JOIN = "JOIN"
    PREDICATE = "PREDICATE"
    OUTPUT = "OUTPUT"

    def name(self) -> str:
        return "gis_spatial_join"

    def displayName(self) -> str:
        return "Spatial Join"

    def shortHelpString(self) -> str:
        return "Join attributes by spatial predicate (native:joinattributesbylocation)."

    def initAlgorithm(self, config: dict[str, Any] | None = None) -> None:
        _ = config
        self.addParameter(QgsProcessingParameterVectorLayer(self.INPUT, "Target layer"))
        self.addParameter(QgsProcessingParameterVectorLayer(self.JOIN, "Join layer"))
        self.addParameter(
            QgsProcessingParameterEnum(
                self.PREDICATE,
                "Geometric predicate",
                options=["intersects", "contains", "within", "touches", "overlaps"],
                defaultValue=0,
            )
        )
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT, "Joined"))

    def _alg_params(self, parameters: dict[str, Any], context: QgsProcessingContext) -> dict[str, Any]:
        return {
            "INPUT": self.parameterAsVectorLayer(parameters, self.INPUT, context),
            "JOIN": self.parameterAsVectorLayer(parameters, self.JOIN, context),
            "PREDICATE": [self.parameterAsEnum(parameters, self.PREDICATE, context)],
            "JOIN_FIELDS": [],
            "METHOD": 0,
            "OUTPUT": "memory:",
        }

    def processAlgorithm(
        self, parameters: dict[str, Any], context: QgsProcessingContext, feedback: QgsProcessingFeedback
    ) -> dict[str, Any]:
        result = self._run_pinned(parameters, context, feedback)
        return {self.OUTPUT: result["OUTPUT"]}


GIS_ANALYSIS_ALGORITHMS: tuple[type[GisAnalysisBase], ...] = (
    BufferAlgorithm,
    IntersectionAlgorithm,
    DissolveAlgorithm,
    ZonalStatisticsAlgorithm,
    SpatialJoinAlgorithm,
)

__all__ = [
    "GIS_PINS",
    "GisAnalysisBase",
    "BufferAlgorithm",
    "IntersectionAlgorithm",
    "DissolveAlgorithm",
    "ZonalStatisticsAlgorithm",
    "SpatialJoinAlgorithm",
    "GIS_ANALYSIS_ALGORITHMS",
]
