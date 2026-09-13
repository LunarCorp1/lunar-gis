"""Minimal QGIS plugin shell for Lunar GIS."""

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import QgsProject


class LunarGIS:
    """Plugin entry point."""

    def __init__(self, iface):
        self.iface = iface
        self.action = None

    def initGui(self):
        self.action = QAction(QIcon(":/plugins/lunar_gis/icon.svg"), "Lunar GIS", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&Lunar GIS", self.action)

    def run(self):
        project = QgsProject.instance()
        layer_count = len(project.mapLayers())
        QMessageBox.information(
            self.iface.mainWindow(),
            "Lunar GIS",
            f"Lunar GIS foundation loaded. Current project has {layer_count} layer(s).",
        )

    def unload(self):
        if self.action is not None:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginMenu("&Lunar GIS", self.action)
            self.action.deleteLater()
