import pytest

from lunar_gis.agent.registry import ToolRegistry, ToolSpec


def noop():
    return None


@pytest.mark.unit
def test_registry_register_and_lookup():
    registry = ToolRegistry()
    registry.register(ToolSpec("project.list_layers", 1, "read", noop))
    assert registry.names() == ("project.list_layers",)
    assert registry.get("project.list_layers").version == 1


@pytest.mark.unit
def test_registry_rejects_duplicate_tool():
    registry = ToolRegistry()
    spec = ToolSpec("project.list_layers", 1, "read", noop)
    registry.register(spec)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(spec)


@pytest.mark.unit
def test_registry_rejects_invalid_risk():
    with pytest.raises(ValueError, match="Invalid risk"):
        ToolRegistry().register(ToolSpec("bad", 1, "danger", noop))


@pytest.mark.unit
def test_registry_get_unknown_raises():
    registry = ToolRegistry()
    with pytest.raises(KeyError, match="Unknown tool"):
        registry.get("missing.tool")


@pytest.mark.unit
def test_registry_names_sorted():
    registry = ToolRegistry()
    registry.register(ToolSpec("b.tool", 1, "read", noop))
    registry.register(ToolSpec("a.tool", 1, "low", noop))
    registry.register(ToolSpec("c.tool", 2, "medium", noop))
    assert registry.names() == ("a.tool", "b.tool", "c.tool")


@pytest.mark.unit
def test_registry_allows_all_valid_risks():
    for risk in ("read", "low", "medium", "high"):
        r = ToolRegistry()
        r.register(ToolSpec(f"t.{risk}", 1, risk, noop))
        assert r.get(f"t.{risk}").risk == risk


@pytest.mark.unit
def test_registry_stores_version_and_handler():
    def handler(x):  # type: ignore[no-untyped-def]
        return x

    spec = ToolSpec("x.y", 3, "high", handler)
    registry = ToolRegistry()
    registry.register(spec)
    got = registry.get("x.y")
    assert got.version == 3
    assert got.handler is handler
    assert got.name == "x.y"


@pytest.mark.unit
def test_toolspec_is_frozen():
    spec = ToolSpec("a.b", 1, "read", noop)
    with pytest.raises(AttributeError):
        spec.name = "other"  # type: ignore[misc]
