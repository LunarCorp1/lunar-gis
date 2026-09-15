"""Minimal, usable QGIS 4 plugin shell for Lunar GIS."""

from pathlib import Path

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction, QDockWidget, QLabel, QVBoxLayout, QWidget
from qgis.core import QgsApplication, QgsProject

from lunar_gis.processing.provider import LunarGISProvider


class LunarGIS:
    """Plugin entry point."""

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None
        self.provider = None

    def initGui(self):
        icon_path = Path(__file__).resolve().parent / "resources" / "icon.svg"
        self.action = QAction(QIcon(str(icon_path)), "Lunar GIS", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.triggered.connect(self.toggle_dock)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&Lunar GIS", self.action)

        self.dock = QDockWidget("Lunar GIS", self.iface.mainWindow())
        self.dock.setObjectName("LunarGISDock")
        self.dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.dock.setWidget(self._build_widget())
        self.iface.mainWindow().addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.dock.hide()
        self.dock.visibilityChanged.connect(self._sync_action)

        self.provider = LunarGISProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def _build_widget(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        title = QLabel("Lunar GIS")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.layer_label = QLabel()
        self.layer_label.setWordWrap(True)
        self._refresh_context()
        layout.addWidget(title)
        layout.addWidget(QLabel("Current QGIS project context"))
        layout.addWidget(self.layer_label)
        layout.addStretch(1)
        return widget

    def _refresh_context(self):
        project = QgsProject.instance()
        layers = list(project.mapLayers().values())
        if not layers:
            self.layer_label.setText("No layers are currently loaded.")
            return
        lines = [f"Layers loaded: {len(layers)}", ""]
        lines.extend(f"• {layer.name()}" for layer in layers[:20])
        if len(layers) > 20:
            lines.append(f"… and {len(layers) - 20} more")
        self.layer_label.setText("\n".join(lines))

    def toggle_dock(self, checked):
        if self.dock is None:
            return
        self._refresh_context()
        self.dock.setVisible(checked)

    def _sync_action(self, visible):
        if self.action is not None:
            self.action.setChecked(visible)

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
        if self.dock is not None:
            self.iface.mainWindow().removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.action is not None:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginMenu("&Lunar GIS", self.action)
            self.action.deleteLater()
            self.action = None
