"""Lunar GIS QGIS plugin package."""


def classFactory(iface):
    from .plugin import LunarGIS

    return LunarGIS(iface)
