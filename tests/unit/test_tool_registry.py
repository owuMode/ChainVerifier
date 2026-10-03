# tests/unit/test_tool_registry.py
from pathlib import Path

from tools.registry import ToolRegistry, discover_tools


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_discovery_finds_real_tools():
    registry = ToolRegistry()
    discover_tools(_project_root() / "tools", registry)
    registry.seal()

    # At least these should be registered.
    assert registry.has("datetime")
    assert registry.has("system_info")
    assert registry.has("filesystem")

    ids = registry.tool_ids()
    assert "datetime" in ids
    assert "system_info" in ids
    assert "filesystem" in ids
    assert len(registry) >= 3


def test_registry_seals():
    registry = ToolRegistry()
    discover_tools(_project_root() / "tools", registry)
    registry.seal()
    try:
        from tools.base import ToolRequest, ToolResult

        class _Dummy:
            @property
            def spec(self):  # pragma: no cover
                raise NotImplementedError

            def execute(self, request: ToolRequest) -> ToolResult:  # pragma: no cover
                raise NotImplementedError

            def verify(self, request: ToolRequest, result: ToolResult) -> bool:  # pragma: no cover
                raise NotImplementedError

        registry.register(_Dummy())  # type: ignore[arg-type]
    except RuntimeError as exc:
        assert "sealed" in str(exc)
    else:
        raise AssertionError("expected registry to be sealed")


def test_datetime_spec_metadata():
    registry = ToolRegistry()
    discover_tools(_project_root() / "tools", registry)
    registry.seal()

    tool = registry.require("datetime")
    spec = tool.spec
    assert spec.tool_id == "datetime"
    assert spec.permission_level.label() == "SAFE"
    assert spec.denied is False
    assert spec.input_schema["type"] == "object"


def test_filesystem_spec_metadata():
    registry = ToolRegistry()
    discover_tools(_project_root() / "tools", registry)
    registry.seal()

    tool = registry.require("filesystem")
    spec = tool.spec
    assert spec.tool_id == "filesystem"
    assert spec.permission_level.label() == "MODERATE"
    assert spec.denied is False
    assert spec.input_schema["type"] == "object"
    assert "action" in spec.input_schema["required"]
    assert "path" in spec.input_schema["required"]