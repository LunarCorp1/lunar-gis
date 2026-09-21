"""QGIS Processing algorithms for the M4-T04 transformation ops.

One thin algorithm per §8 op, each delegating GIS math to the pinned
native/GDAL algorithm. These algorithms are the Processing-toolbox face
of the transformation boundary; the governed ``data.run_transformation``
tool executes the same pins through ``transform_qgis.run_chain``.

Public API:
- TransformAlgorithmBase + 7 subclasses
- TRANSFORM_ALGORITHMS: tuple of algorithm classes
"""

from __future__ import annotations

from typing import Any

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingOutputVectorLayer,
    QgsProcessingOutputRasterLayer,
    QgsProcessingParameterCrs,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
)

from lunar_gis.data.transforms import EXECUTOR_PINS, TransformOp


class TransformAlgorithmBase(QgsProcessingAlgorithm):
    """Shared boilerplate for transformation algorithms."""

    OP = ""
    GROUP_NAME = "Transformations"
    GROUP_ID = "transformations"

    def createInstance(self) -> TransformAlgorithmBase:
        return type(self)()

    def group(self) -> str:
        return self.GROUP_NAME

    def groupId(self) -> str:
        return self.GROUP_ID

    def _run_pinned(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        import processing  # type: ignore[import-not-found]

        alg_id, alg_version = EXECUTOR_PINS[self.OP]
        alg_params = self._alg_params(parameters, context)
        feedback.pushInfo(f"Lunar GIS {self.OP} via {alg_id}@{alg_version}")
        try:
            result = processing.run(alg_id, alg_params, context=context, feedback=feedback)
            return dict(result)
        except Exception as exc:
            raise QgsProcessingException(f"{self.OP} failed: {exc}") from exc

    def _alg_params(self, parameters: dict[str, Any], context: QgsProcessingContext) -> dict[str, Any]:
        raise NotImplementedError


class ReprojectVectorAlgorithm(TransformAlgorithmBase):
    OP = TransformOp.REPROJECT_VECTOR.value
    INPUT = "INPUT"
    TARGET_CRS = "TARGET_CRS"
    OUTPUT = "OUTPUT"

    def name(self) -> str:
        return "reproject_vector"

    def displayName(self) -> str:
        return "Reproject Vector Layer"

    def shortHelpString(self) -> str:
        return "Reproject a vector layer to a target CRS (native:reprojectlayer)."

    def initAlgorithm(self, config: dict[str, Any] | None = None) -> None:
        _ = config
        self.addParameter(QgsProcessingParameterVectorLayer(self.INPUT, "Input vector layer"))
        self.addParameter(QgsProcessingParameterCrs(self.TARGET_CRS, "Target CRS"))
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT, "Reprojected"))

    def _alg_params(self, parameters: dict[str, Any], context: QgsProcessingContext) -> dict[str, Any]:
        return {
            "INPUT": self.parameterAsVectorLayer(parameters, self.INPUT, context),
            "TARGET_CRS": self.parameterAsCrs(parameters, self.TARGET_CRS, context),
            "OUTPUT": "memory:",
        }

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        result = self._run_pinned(parameters, context, feedback)
        return {self.OUTPUT: result["OUTPUT"]}


class ReprojectRasterAlgorithm(TransformAlgorithmBase):
    OP = TransformOp.REPROJECT_RASTER.value
    INPUT = "INPUT"
    TARGET_CRS = "TARGET_CRS"
    RESAMPLING = "RESAMPLING"
    OUTPUT = "OUTPUT"

    def name(self) -> str:
        return "reproject_raster"

    def displayName(self) -> str:
        return "Reproject Raster Layer"

    def shortHelpString(self) -> str:
        return "Warp a raster to a target CRS with explicit resampling (gdal:warpreproject)."

    def initAlgorithm(self, config: dict[str, Any] | None = None) -> None:
        _ = config
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT, "Input raster layer"))
        self.addParameter(QgsProcessingParameterCrs(self.TARGET_CRS, "Target CRS"))
        self.addParameter(QgsProcessingParameterString(self.RESAMPLING, "Resampling method", defaultValue="bilinear"))
        self.addOutput(QgsProcessingOutputRasterLayer(self.OUTPUT, "Reprojected"))

    def _alg_params(self, parameters: dict[str, Any], context: QgsProcessingContext) -> dict[str, Any]:
        return {
            "INPUT": self.parameterAsRasterLayer(parameters, self.INPUT, context),
            "TARGET_CRS": self.parameterAsCrs(parameters, self.TARGET_CRS, context),
            "RESAMPLING": self.parameterAsString(parameters, self.RESAMPLING, context),
            "OUTPUT": "memory:",
        }

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        result = self._run_pinned(parameters, context, feedback)
        return {self.OUTPUT: result["OUTPUT"]}


class ClipAlgorithm(TransformAlgorithmBase):
    OP = TransformOp.CLIP.value
    INPUT = "INPUT"
    OVERLAY = "OVERLAY"
    OUTPUT = "OUTPUT"

    def name(self) -> str:
        return "clip_layer"

    def displayName(self) -> str:
        return "Clip Vector Layer"

    def shortHelpString(self) -> str:
        return "Spatial subset of a vector layer by an overlay layer (native:clip)."

    def initAlgorithm(self, config: dict[str, Any] | None = None) -> None:
        _ = config
        self.addParameter(QgsProcessingParameterVectorLayer(self.INPUT, "Input layer"))
        self.addParameter(QgsProcessingParameterVectorLayer(self.OVERLAY, "Overlay (clip) layer"))
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT, "Clipped"))

    def _alg_params(self, parameters: dict[str, Any], context: QgsProcessingContext) -> dict[str, Any]:
        return {
            "INPUT": self.parameterAsVectorLayer(parameters, self.INPUT, context),
            "OVERLAY": self.parameterAsVectorLayer(parameters, self.OVERLAY, context),
            "OUTPUT": "memory:",
        }

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        result = self._run_pinned(parameters, context, feedback)
        return {self.OUTPUT: result["OUTPUT"]}


class FilterAlgorithm(TransformAlgorithmBase):
    OP = TransformOp.FILTER.value
    INPUT = "INPUT"
    FIELD = "FIELD"
    OPERATOR = "OPERATOR"
    VALUE = "VALUE"
    OUTPUT = "OUTPUT"

    def name(self) -> str:
        return "filter_features"

    def displayName(self) -> str:
        return "Filter Features by Attribute"

    def shortHelpString(self) -> str:
        return "Attribute subset with a structured predicate (field + operator + value; native:extractbyexpression)."

    def initAlgorithm(self, config: dict[str, Any] | None = None) -> None:
        _ = config
        self.addParameter(QgsProcessingParameterVectorLayer(self.INPUT, "Input layer"))
        self.addParameter(QgsProcessingParameterField(self.FIELD, "Field", parentLayerParameterName=self.INPUT))
        self.addParameter(QgsProcessingParameterString(self.OPERATOR, "Operator", defaultValue="="))
        self.addParameter(QgsProcessingParameterString(self.VALUE, "Value", defaultValue="", optional=True))
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT, "Filtered"))

    def _alg_params(self, parameters: dict[str, Any], context: QgsProcessingContext) -> dict[str, Any]:
        from lunar_gis.data.transforms import FilterPredicate

        predicate = FilterPredicate(
            field=self.parameterAsString(parameters, self.FIELD, context),
            op=self.parameterAsString(parameters, self.OPERATOR, context),
            value=self.parameterAsString(parameters, self.VALUE, context),
        )
        return {
            "INPUT": self.parameterAsVectorLayer(parameters, self.INPUT, context),
            "EXPRESSION": predicate.to_expression(),
            "OUTPUT": "memory:",
        }

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        result = self._run_pinned(parameters, context, feedback)
        return {self.OUTPUT: result["OUTPUT"]}


class JoinAlgorithm(TransformAlgorithmBase):
    OP = TransformOp.JOIN.value
    INPUT = "INPUT"
    TARGET_FIELD = "TARGET_FIELD"
    JOIN_LAYER = "JOIN_LAYER"
    JOIN_FIELD = "JOIN_FIELD"
    OUTPUT = "OUTPUT"

    def name(self) -> str:
        return "join_attributes"

    def displayName(self) -> str:
        return "Join Attributes (1:1)"

    def shortHelpString(self) -> str:
        return "Attribute-only 1:1 join (native:joinattributestable). 1:N and null keys are rejected."

    def initAlgorithm(self, config: dict[str, Any] | None = None) -> None:
        _ = config
        self.addParameter(QgsProcessingParameterVectorLayer(self.INPUT, "Target layer"))
        self.addParameter(
            QgsProcessingParameterField(self.TARGET_FIELD, "Target field", parentLayerParameterName=self.INPUT)
        )
        self.addParameter(QgsProcessingParameterVectorLayer(self.JOIN_LAYER, "Join layer"))
        self.addParameter(
            QgsProcessingParameterField(self.JOIN_FIELD, "Join field", parentLayerParameterName=self.JOIN_LAYER)
        )
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT, "Joined"))

    def _alg_params(self, parameters: dict[str, Any], context: QgsProcessingContext) -> dict[str, Any]:
        return {
            "INPUT": self.parameterAsVectorLayer(parameters, self.INPUT, context),
            "FIELD": self.parameterAsString(parameters, self.TARGET_FIELD, context),
            "INPUT_2": self.parameterAsVectorLayer(parameters, self.JOIN_LAYER, context),
            "FIELD_2": self.parameterAsString(parameters, self.JOIN_FIELD, context),
            "OUTPUT": "memory:",
        }

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        result = self._run_pinned(parameters, context, feedback)
        return {self.OUTPUT: result["OUTPUT"]}


class RasterToVectorAlgorithm(TransformAlgorithmBase):
    OP = TransformOp.RASTER_TO_VECTOR.value
    INPUT = "INPUT"
    FIELD = "FIELD"
    OUTPUT = "OUTPUT"

    def name(self) -> str:
        return "raster_to_vector"

    def displayName(self) -> str:
        return "Polygonize Raster"

    def shortHelpString(self) -> str:
        return "Convert raster zones to vector polygons with explicit field (gdal:polygonize)."

    def initAlgorithm(self, config: dict[str, Any] | None = None) -> None:
        _ = config
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT, "Input raster"))
        self.addParameter(QgsProcessingParameterString(self.FIELD, "Output field name", defaultValue="DN"))
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT, "Vectorized"))

    def _alg_params(self, parameters: dict[str, Any], context: QgsProcessingContext) -> dict[str, Any]:
        return {
            "INPUT": self.parameterAsRasterLayer(parameters, self.INPUT, context),
            "FIELD": self.parameterAsString(parameters, self.FIELD, context),
            "OUTPUT": "memory:",
        }

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        result = self._run_pinned(parameters, context, feedback)
        return {self.OUTPUT: result["OUTPUT"]}


class VectorToRasterAlgorithm(TransformAlgorithmBase):
    OP = TransformOp.VECTOR_TO_RASTER.value
    INPUT = "INPUT"
    RESOLUTION = "RESOLUTION"
    ATTRIBUTE = "ATTRIBUTE"
    OUTPUT = "OUTPUT"

    def name(self) -> str:
        return "vector_to_raster"

    def displayName(self) -> str:
        return "Rasterize Vector"

    def shortHelpString(self) -> str:
        return "Burn vector attributes to raster with explicit resolution (gdal:rasterize)."

    def initAlgorithm(self, config: dict[str, Any] | None = None) -> None:
        _ = config
        self.addParameter(QgsProcessingParameterVectorLayer(self.INPUT, "Input vector"))
        self.addParameter(
            QgsProcessingParameterNumber(
                self.RESOLUTION, "Target resolution", type=QgsProcessingParameterNumber.Double, defaultValue=10.0
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.ATTRIBUTE,
                "Burn attribute",
                parentLayerParameterName=self.INPUT,
                optional=True,
            )
        )
        self.addOutput(QgsProcessingOutputRasterLayer(self.OUTPUT, "Rasterized"))

    def _alg_params(self, parameters: dict[str, Any], context: QgsProcessingContext) -> dict[str, Any]:
        out: dict[str, Any] = {
            "INPUT": self.parameterAsVectorLayer(parameters, self.INPUT, context),
            "OUTPUT": "memory:",
            "UNITS": 1,
            "WIDTH": self.parameterAsDouble(parameters, self.RESOLUTION, context),
            "HEIGHT": self.parameterAsDouble(parameters, self.RESOLUTION, context),
        }
        attr = self.parameterAsString(parameters, self.ATTRIBUTE, context)
        if attr:
            out["FIELD"] = attr
        return out

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        result = self._run_pinned(parameters, context, feedback)
        return {self.OUTPUT: result["OUTPUT"]}


TRANSFORM_ALGORITHMS: tuple[type[TransformAlgorithmBase], ...] = (
    ReprojectVectorAlgorithm,
    ReprojectRasterAlgorithm,
    ClipAlgorithm,
    FilterAlgorithm,
    JoinAlgorithm,
    RasterToVectorAlgorithm,
    VectorToRasterAlgorithm,
)


__all__ = [
    "TransformAlgorithmBase",
    "ReprojectVectorAlgorithm",
    "ReprojectRasterAlgorithm",
    "ClipAlgorithm",
    "FilterAlgorithm",
    "JoinAlgorithm",
    "RasterToVectorAlgorithm",
    "VectorToRasterAlgorithm",
    "TRANSFORM_ALGORITHMS",
]
