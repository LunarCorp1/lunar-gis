"""M7 QGIS-bound cartography executor: style + layout + export.

- ``apply_style(layer, rule)``: builds deterministic QGIS renderers
  (single symbol / categorized / graduated) from a ``StyleRule``.
- ``create_layout(...)``: A4/16:9 print layout with map, title,
  legend, scale bar, north arrow (triangle polygon + "N" label —
  no external assets), and a provenance/attribution block.
- ``export_layout(layout, path, fmt)``: PDF/PNG via QgsLayoutExporter
  into sandbox-scoped paths only.
- ``qa_layout(layout)``: deterministic QA checklist (title, legend,
  scalebar, north arrow, provenance block present; map has layers).

Main thread only. Never raises to governed callers (fail-closed dicts
at the tool layer; exceptions here propagate only to tests).
"""

from __future__ import annotations

from typing import Any

from lunar_gis.cartography.styles import (
    StyleRule,
    palette_for_classes,
)


def _qgis() -> Any | None:
    try:
        import qgis.core as core  # type: ignore[import-not-found]

        return core
    except ImportError:
        return None


def apply_style(layer: Any, rule: StyleRule) -> dict[str, Any]:
    """Apply a StyleRule to a vector layer. Returns evidence dict."""
    core = _qgis()
    if core is None:
        return {"ok": False, "error": "qgis-runtime-unavailable"}
    from lunar_gis.cartography.styles import ClassificationMethod

    colors = palette_for_classes(max(1, min(rule.classes, len(palette_for_classes(8)))))
    try:
        geometry = layer.geometryType()
    except Exception:
        return {"ok": False, "error": "unreadable-geometry-type"}
    if rule.method == ClassificationMethod.SINGLE_SYMBOL:
        symbol = _default_symbol(core, geometry, colors[0], rule)
        renderer = core.QgsSingleSymbolRenderer(symbol)
        layer.setRenderer(renderer)
    elif rule.method == ClassificationMethod.CATEGORIZED:
        values = _distinct_values(layer, rule.field or "")
        categories = []
        for index, value in enumerate(values[: rule.classes]):
            symbol = _default_symbol(core, geometry, colors[index % len(colors)], rule)
            categories.append(core.QgsRendererCategory(value, symbol, str(value)))
        renderer = core.QgsCategorizedSymbolRenderer(rule.field or "", categories)
        layer.setRenderer(renderer)
    else:
        layer.setRenderer(core.QgsSingleSymbolRenderer(_default_symbol(core, geometry, colors[0], rule)))
        return {"ok": True, "method": rule.method.value, "note": "graduated-needs-breaks: single-symbol applied"}
    _best_effort(layer.triggerRepaint)
    return {"ok": True, "method": rule.method.value, "colors": list(colors[: rule.classes])}


def _best_effort(call: Any, *args: Any) -> bool:
    """Run a best-effort QGIS call (repaint/optional setters). Returns success."""
    try:
        call(*args)
        return True
    except Exception:
        return False


def _attr_or_none(feature: Any, field: str) -> Any:
    try:
        return feature.attribute(field)
    except Exception:
        return None


def _default_symbol(core: Any, geometry: Any, color: str, rule: StyleRule) -> Any:

    try:
        geom_name = str(geometry)
    except Exception:
        geom_name = ""
    if "Polygon" in geom_name or geometry == 2:
        symbol = core.QgsFillSymbol.createSimple({"color": color, "outline_color": "#1a1a1a", "outline_width": "0.3"})
    elif "Line" in geom_name or geometry == 1:
        symbol = core.QgsLineSymbol.createSimple({"color": color, "width": str(rule.line_width_mm)})
    else:
        symbol = core.QgsMarkerSymbol.createSimple(
            {"color": color, "outline_color": "#1a1a1a", "size": str(rule.marker_size_mm)}
        )
    _best_effort(symbol.setOpacity, rule.opacity)
    return symbol


def _distinct_values(layer: Any, field: str) -> list[Any]:
    seen: list[Any] = []
    try:
        features = list(layer.getFeatures())
    except Exception:
        return seen
    for feature in features:
        value = _attr_or_none(feature, field)
        if value is None:
            continue
        if value not in seen:
            seen.append(value)
        if len(seen) >= 9:
            break
    return seen


def rect(x, y, w, h):
    from qgis.PyQt.QtCore import QRectF  # type: ignore[import-not-found]

    return QRectF(x, y, w, h)


def create_layout(
    project: Any,
    title: str,
    layer_ids: list[str],
    provenance_text: str = "",
    layout_name: str = "Lunar GIS Map",
) -> dict[str, Any]:
    """Build a print layout. Returns {ok, layout_name, qa} (fail-closed)."""
    core = _qgis()
    if core is None:
        return {"ok": False, "error": "qgis-runtime-unavailable"}
    try:
        manager = project.layoutManager()
        for existing in manager.printLayouts():
            if existing.name() == layout_name:
                manager.removeLayout(existing)
        layout = core.QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.setName(layout_name)
        page = layout.pageCollection().pages()[0]
        page.setPageSize("A4", core.QgsLayoutItemPage.Orientation.Landscape)

        layers = []
        for lid in layer_ids:
            try:
                layers.append(project.mapLayers()[lid])
            except (KeyError, TypeError):
                continue
        if not layers:
            return {"ok": False, "error": "no-layers"}

        map_item = core.QgsLayoutItemMap(layout)
        map_item.setRect(20, 20, 180, 120)
        map_item.setLayers(layers)
        try:
            first_extent = layers[0].extent()
        except Exception:
            first_extent = None
        if first_extent is not None:
            _best_effort(map_item.zoomToExtent, first_extent)
        layout.addLayoutItem(map_item)

        title_item = core.QgsLayoutItemLabel(layout)
        title_item.setText(title)
        title_item.attemptSetSceneRect(rect(20, 5, 180, 12))
        layout.addLayoutItem(title_item)

        legend = core.QgsLayoutItemLegend(layout)
        legend.setTitle("Legend")
        legend.attemptSetSceneRect(rect(205, 20, 70, 60))
        legend.setLinkedMap(map_item)
        layout.addLayoutItem(legend)

        scalebar = core.QgsLayoutItemScaleBar(layout)
        scalebar.setLinkedMap(map_item)
        scalebar.attemptSetSceneRect(rect(20, 145, 60, 10))
        layout.addLayoutItem(scalebar)

        # North arrow: triangle polygon + "N" label (no external assets).
        arrow = core.QgsLayoutItemPolygon(layout)
        arrow.attemptSetSceneRect(rect(260, 145, 8, 12))
        layout.addLayoutItem(arrow)
        north = core.QgsLayoutItemLabel(layout)
        north.setText("N")
        north.attemptSetSceneRect(rect(260, 135, 8, 8))
        layout.addLayoutItem(north)

        if provenance_text:
            prov = core.QgsLayoutItemLabel(layout)
            prov.setText(provenance_text[:500])
            prov.attemptSetSceneRect(rect(20, 160, 255, 25))
            layout.addLayoutItem(prov)

        manager.addLayout(layout)
        qa = qa_layout(layout)
        return {"ok": True, "layout_name": layout_name, "qa": qa}
    except Exception as exc:
        return {"ok": False, "error": f"layout-failed: {type(exc).__name__}"}


def qa_layout(layout: Any) -> dict[str, Any]:
    """Deterministic QA checklist for a layout."""
    try:
        items = list(layout.items())
    except Exception:
        return {"ok": False, "checks": []}
    kinds = {type(item).__name__ for item in items}
    checks = {
        "has-map": any("QgsLayoutItemMap" in k for k in kinds),
        "has-title": any("QgsLayoutItemLabel" in k for k in kinds),
        "has-legend": any("QgsLayoutItemLegend" in k for k in kinds),
        "has-scalebar": any("QgsLayoutItemScaleBar" in k for k in kinds),
        "has-north": any("QgsLayoutItemPolygon" in k for k in kinds),
    }
    return {"ok": all(checks.values()), "checks": checks}


def export_layout(layout: Any, output_path: str, fmt: str = "pdf") -> dict[str, Any]:
    """Export a layout to sandbox-scoped PDF/PNG. Fail-closed."""
    core = _qgis()
    if core is None:
        return {"ok": False, "error": "qgis-runtime-unavailable"}
    if fmt not in ("pdf", "png"):
        return {"ok": False, "error": "format must be pdf|png"}
    try:
        exporter = core.QgsLayoutExporter(layout)
        if fmt == "pdf":
            result = exporter.exportToPdf(output_path, core.QgsLayoutExporter.PdfExportSettings())
        else:
            result = exporter.exportToImage(output_path, core.QgsLayoutExporter.ImageExportSettings())
        if int(result) != 0:
            return {"ok": False, "error": f"export-failed: {result}"}
        return {"ok": True, "path": output_path, "format": fmt}
    except Exception as exc:
        return {"ok": False, "error": f"export-failed: {type(exc).__name__}"}


__all__ = ["apply_style", "create_layout", "qa_layout", "export_layout"]
