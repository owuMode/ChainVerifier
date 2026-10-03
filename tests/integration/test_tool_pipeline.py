# tests/integration/test_tool_pipeline.py
"""
Proves the pipeline that gates every tool call:

    registry lookup → schema validation → policy → execute → verify
"""

from pathlib import Path

from security.policies import PolicyDecision, PolicyEngine
from security.validation import validate
from tools.base import ToolRequest
from tools.registry import ToolRegistry, discover_tools


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_registry() -> ToolRegistry:
    registry = ToolRegistry()
    discover_tools(_project_root() / "tools", registry)
    registry.seal()
    return registry


def test_full_pipeline_datetime_happy_path():
    registry = _load_registry()
    tool = registry.require("datetime")

    request = ToolRequest(tool_id="datetime", arguments={})

    # 1. Schema validation
    assert validate(tool.spec.input_schema, request.arguments) == []

    # 2. Policy gate
    verdict = PolicyEngine().evaluate(
        permission_level=tool.spec.permission_level,
        tool_id=tool.spec.tool_id,
        manifest_denied=tool.spec.denied,
    )
    assert verdict.decision is PolicyDecision.ALLOW

    # 3. Execute
    result = tool.execute(request)
    assert result.ok is True

    # 4. Verify
    assert tool.verify(request, result) is True


def test_full_pipeline_system_info_happy_path():
    registry = _load_registry()
    tool = registry.require("system_info")

    request = ToolRequest(tool_id="system_info", arguments={})

    # 1. Schema validation
    assert validate(tool.spec.input_schema, request.arguments) == []

    # 2. Policy gate
    verdict = PolicyEngine().evaluate(
        permission_level=tool.spec.permission_level,
        tool_id=tool.spec.tool_id,
        manifest_denied=tool.spec.denied,
    )
    assert verdict.decision is PolicyDecision.ALLOW

    # 3. Execute
    result = tool.execute(request)
    assert result.ok is True

    # 4. Verify
    assert tool.verify(request, result) is True


def test_schema_rejects_unexpected_property():
    registry = _load_registry()
    tool = registry.require("datetime")

    # datetime schema has additionalProperties: false
    errors = validate(tool.spec.input_schema, {"unexpected": "x"})
    assert errors, "additionalProperties should be rejected"