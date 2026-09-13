import pytest

from lunar_gis.agent.registry import ToolRegistry, ToolSpec


def noop():
    return None


def test_registry_register_and_lookup():
    registry = ToolRegistry()
    registry.register(ToolSpec("project.list_layers", 1, "read", noop))
    assert registry.names() == ("project.list_layers",)
    assert registry.get("project.list_layers").version == 1


def test_registry_rejects_duplicate_tool():
    registry = ToolRegistry()
    spec = ToolSpec("project.list_layers", 1, "read", noop)
    registry.register(spec)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(spec)


def test_registry_rejects_invalid_risk():
    with pytest.raises(ValueError, match="Invalid risk"):
        ToolRegistry().register(ToolSpec("bad", 1, "danger", noop))
