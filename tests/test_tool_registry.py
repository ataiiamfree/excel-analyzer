from app.tools.registry import UnknownToolError, build_default_tool_registry


def test_default_registry_exposes_planner_tools_by_skill():
    registry = build_default_tool_registry()

    spreadsheet_tools = registry.planner_tools("spreadsheet_analysis")
    artifact_tools = registry.planner_tools("artifact_qa")

    assert [tool.name for tool in spreadsheet_tools] == ["python"]
    assert [tool.name for tool in artifact_tools] == ["artifact_qa"]


def test_registry_normalizes_aliases():
    registry = build_default_tool_registry()

    assert registry.normalize_name("code.run_python_sandboxed") == "python"
    assert registry.has("artifact.explain")
    assert registry.get("artifact.explain").name == "artifact_qa"


def test_registry_rejects_unknown_tool():
    registry = build_default_tool_registry()

    try:
        registry.ensure_registered("knowledge")
    except UnknownToolError as exc:
        assert "knowledge" in str(exc)
    else:
        raise AssertionError("knowledge should not be registered by default")
