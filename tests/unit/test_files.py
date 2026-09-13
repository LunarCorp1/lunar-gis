from pathlib import Path


def test_expected_foundation_files_exist():
    expected = [
        "AGENTS.md",
        "metadata.txt",
        "README.md",
        "lunar_gis/__init__.py",
        "lunar_gis/plugin.py",
        ".opencode/agents/architect.md",
        ".opencode/skills/qgis-plugin-development/SKILL.md",
    ]
    for path in expected:
        assert Path(path).exists(), path
