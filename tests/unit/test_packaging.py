"""Packaging boundary tests for P0-T02/P0-T03."""

import configparser
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LUNAR = ROOT / "lunar_gis"

# Python 3.11+ has tomllib in stdlib; fallback to tomli for 3.10
try:
    import tomllib  # type: ignore
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore


def test_all_bounded_modules_importable():
    # Pure python import check — no QGIS required
    import lunar_gis
    import lunar_gis.ai  # noqa: F401
    import lunar_gis.analysis  # noqa: F401
    import lunar_gis.cartography  # noqa: F401
    import lunar_gis.data  # noqa: F401
    import lunar_gis.provenance  # noqa: F401
    import lunar_gis.reports  # noqa: F401
    import lunar_gis.ui  # noqa: F401
    import lunar_gis.utils  # noqa: F401
    import lunar_gis.project.context  # noqa: F401
    import lunar_gis.agent.registry  # noqa: F401

    # Verify __init__.py exists for each bounded module (except resources)
    for mod in ["ai", "analysis", "cartography", "data", "provenance", "reports", "ui", "utils"]:
        assert (LUNAR / mod / "__init__.py").exists(), f"missing {mod}/__init__.py"
        # docstring check — file should not be empty and contain no side-effect imports
        text = (LUNAR / mod / "__init__.py").read_text(encoding="utf-8")
        assert text.startswith('"""'), f"{mod}/__init__.py missing docstring"
        # ensure no qgis import in placeholder
        assert "import qgis" not in text.lower()
        assert "from qgis" not in text.lower()


def test_version_single_source():
    # lunar_gis/__version__.py is canonical
    version_file = LUNAR / "__version__.py"
    assert version_file.exists()
    text = version_file.read_text(encoding="utf-8")
    assert 'import qgis' not in text.lower()
    # Extract version via regex
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    assert m, "could not parse __version__"
    version_py = m.group(1)
    # Do not hardcode literal in assertion — derive from file, but sanity check non-empty
    assert re.match(r"^\d+\.\d+\.\d+$", version_py), version_py

    # Also verify import works
    from lunar_gis.__version__ import __version__

    assert __version__ == version_py

    # pyproject.toml must use dynamic version attr pointing to __version__ — semantic check via tomllib
    with open(ROOT / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    assert "version" in data.get("project", {}).get("dynamic", []), "project.dynamic must contain version"
    assert data.get("tool", {}).get("setuptools", {}).get("dynamic", {}).get("version", {}).get("attr") == "lunar_gis.__version__.__version__"
    # ensure no static version under [project]
    assert "version" not in data.get("project", {}), "project.version should be absent when dynamic"
    # also keep substring guard for readability
    pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'lunar_gis.__version__' in pyproject_text


def test_metadata_exists_canonical_and_root_sync():
    canonical = LUNAR / "metadata.txt"
    root = ROOT / "metadata.txt"
    assert canonical.exists(), "lunar_gis/metadata.txt missing"
    assert root.exists(), "root metadata.txt missing"
    # Must be byte-equal (deterministic copy)
    assert canonical.read_bytes() == root.read_bytes(), "metadata.txt copies diverged"


def test_metadata_urls_and_fields():
    cfg = configparser.ConfigParser()
    # metadata.txt is not strictly INI but configparser handles it (no interpolation)
    cfg.read(LUNAR / "metadata.txt", encoding="utf-8")
    general = cfg["general"]
    # URLs must be LunarCorp1, not LunarB
    assert "LunarCorp1" in general["repository"], general["repository"]
    assert "LunarCorp1" in general["tracker"]
    assert "LunarCorp1" in general["source"]
    assert general["repository"] == "https://github.com/LunarCorp1/lunar-gis"
    assert "LunarB" not in general["repository"]
    # Required fields
    assert general["name"] == "Lunar GIS"
    assert general["icon"] == "resources/icon.svg"
    assert general["qgisMinimumVersion"] == "4.0"
    assert general["category"] == "Analysis"


def test_metadata_version_matches_version_py():
    cfg = configparser.ConfigParser()
    cfg.read(LUNAR / "metadata.txt", encoding="utf-8")
    meta_version = cfg["general"]["version"]
    from lunar_gis.__version__ import __version__

    assert meta_version == __version__
    # Also check root matches
    cfg2 = configparser.ConfigParser()
    cfg2.read(ROOT / "metadata.txt", encoding="utf-8")
    assert cfg2["general"]["version"] == __version__


def test_icon_exists_packaged_location():
    icon = LUNAR / "resources" / "icon.svg"
    assert icon.exists(), "lunar_gis/resources/icon.svg missing"
    content = icon.read_text(encoding="utf-8")
    assert "<svg" in content
    # Old locations must be gone (Option B)
    assert not (ROOT / "resources.qrc").exists(), "dead resources.qrc should be removed"
    assert not (ROOT / "resources" / "icon.svg").exists(), "old resources/icon.svg should be removed"
    # resources dir must not be a python package (no __init__.py)
    assert not (LUNAR / "resources" / "__init__.py").exists()


def test_plugin_resolves_resource_via_parent():
    text = (LUNAR / "plugin.py").read_text(encoding="utf-8")
    # Must use parent (installed layout) not parent.parent (repo checkout)
    assert 'Path(__file__).resolve().parent / "resources" / "icon.svg"' in text
    assert 'parent.parent / "resources"' not in text
    # Verify file path actually resolves
    plugin_path = LUNAR / "plugin.py"
    resolved_icon = (plugin_path.parent / "resources" / "icon.svg").resolve()
    assert resolved_icon.exists()


def test_pyproject_package_discovery():
    with open(ROOT / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    find = data.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {})
    assert find.get("include") == ["lunar_gis*"]
    package_data = data.get("tool", {}).get("setuptools", {}).get("package-data", {})
    assert package_data.get("lunar_gis") == ["metadata.txt", "resources/*", "LICENSE*"]
    # License-files should be under [project] (PEP 639) — check correct location
    assert data.get("project", {}).get("license-files") == ["LICENSE*"]
    # Ensure old single-package flat list removed — packages must be a dict with find, not a list
    packages_raw = data.get("tool", {}).get("setuptools", {}).get("packages")
    assert isinstance(packages_raw, dict) and "find" in packages_raw, "packages should be find dict, not flat list"
    # Also substring check for human readability
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'include = ["lunar_gis*"]' in text
    assert 'packages = ["lunar_gis"]' not in text


def test_icon_accessible_via_importlib_resources():
    """Verify icon is accessible as package data after editable install (real artifact)."""
    try:
        from importlib.resources import files  # Python 3.9+
    except ImportError:
        from importlib_resources import files  # type: ignore

    icon = files("lunar_gis") / "resources" / "icon.svg"
    assert icon.is_file(), f"importlib.resources icon missing: {icon}"
    assert "<svg" in icon.read_text(encoding="utf-8")


def test_installed_version_matches_metadata():
    """Real artifact check: importlib.metadata version matches __version__ and metadata.txt."""
    from importlib.metadata import version as pkg_version

    from lunar_gis.__version__ import __version__

    assert pkg_version("lunar-gis") == __version__
    cfg = configparser.ConfigParser()
    cfg.read(LUNAR / "metadata.txt", encoding="utf-8")
    assert cfg["general"]["version"] == __version__


def test_qgis_plugin_zip_structure(tmp_path):
    """Build a QGIS plugin ZIP structurally and inspect contents without QGIS runtime."""
    zip_path = tmp_path / "lunar_gis.zip"
    # Use zipfile to mimic `zip -r` — include only tracked package files
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in LUNAR.rglob("*"):
            if p.is_dir():
                continue
            if "__pycache__" in p.parts:
                continue
            # Only include files that would be part of plugin (exclude .pyc)
            if p.suffix == ".pyc":
                continue
            arcname = p.relative_to(ROOT).as_posix()
            # For QGIS ZIP, the top-level folder should be lunar_gis/
            # ensure arcname starts with lunar_gis/
            assert arcname.startswith("lunar_gis/")
            z.write(p, arcname)
        # Also ensure root metadata.txt is not inside ZIP as duplicate top-level?
        # QGIS ZIP should not have metadata at repo root inside ZIP, only inside lunar_gis
        # Our ZIP currently only includes lunar_gis/*, so correct.

    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        # Required plugin files
        assert "lunar_gis/__init__.py" in names
        assert "lunar_gis/plugin.py" in names
        assert "lunar_gis/metadata.txt" in names
        assert "lunar_gis/resources/icon.svg" in names
        assert "lunar_gis/__version__.py" in names
        for mod in ["ai", "analysis", "cartography", "data", "provenance", "reports", "ui", "utils"]:
            assert f"lunar_gis/{mod}/__init__.py" in names, f"missing {mod} in zip"
        # Must NOT contain dead QRC or old resource path
        assert "resources.qrc" not in names
        assert "resources/icon.svg" not in names
        # Must contain classFactory
        init_text = z.read("lunar_gis/__init__.py").decode()
        assert "def classFactory" in init_text
        # metadata inside ZIP must have correct repository URL
        meta = z.read("lunar_gis/metadata.txt").decode()
        assert "LunarCorp1" in meta
        assert "LunarB" not in meta
