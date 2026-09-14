"""Deterministic summaries of the current QGIS project."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LayerSummary:
    layer_id: str
    name: str
    provider: str
    geometry_type: str | None = None
    crs_authid: str | None = None
    feature_count: int | None = None


class ProjectContext:
    """Build a compact context representation without sending project data anywhere."""

    def __init__(self, project):
        self.project = project

    def layer_summaries(self) -> list[LayerSummary]:
        summaries: list[LayerSummary] = []
        for layer in self.project.mapLayers().values():
            geometry_type = None
            feature_count = None
            if hasattr(layer, "geometryType"):
                try:
                    geometry_type = str(layer.geometryType())
                except Exception:
                    geometry_type = None
            if hasattr(layer, "featureCount"):
                try:
                    feature_count = int(layer.featureCount())
                except Exception:
                    feature_count = None
            crs_authid = None
            try:
                crs_authid = layer.crs().authid()
            except Exception:
                crs_authid = None  # defensive: invalid CRS or SIP error
            summaries.append(
                LayerSummary(
                    layer_id=layer.id(),
                    name=layer.name(),
                    provider=layer.providerType(),
                    geometry_type=geometry_type,
                    crs_authid=crs_authid,
                    feature_count=feature_count,
                )
            )
        return summaries
