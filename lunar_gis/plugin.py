"""Lunar GIS QGIS 4 plugin shell with the full workspace dock."""

from pathlib import Path

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction, QDockWidget
from qgis.core import QgsApplication

from lunar_gis.processing.provider import LunarGISProvider
from lunar_gis.ui.workspace import LunarGISWorkspace


class LunarGIS:
    """Plugin entry point."""

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None
        self.provider = None
        self.workspace = None

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
        self.workspace = LunarGISWorkspace()
        return self.workspace

    def toggle_dock(self, checked):
        if self.dock is None:
            return
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
