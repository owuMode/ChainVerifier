# tools/registry/registry.py
"""
ToolRegistry — the single source of truth for available tools (spec §21, §22).

Design:
  * No hardcoded list of tools anywhere.
  * Tools are discovered by scanning `tools/*/manifest.yaml`.
  * Each tool is a ToolContract instance exposing:
        tool_id, name, description, category, version,
        permission_level, capabilities, input_schema,
        execute(request) -> ToolResult,
        verify(request, result) -> bool,
        rollback(request, result) -> None  (optional)
  * Registry is read-only after discovery. No dynamic add/remove
    from the agent side.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from security.permissions import PermissionLevel
from tools.base import ToolRequest, ToolResult


@dataclass(frozen=True)
class ToolSpec:
    """Static metadata about a tool. Declared in the manifest."""
    tool_id: str
    name: str
    description: str
    category: str
    version: str
    permission_level: PermissionLevel
    capabilities: tuple[str, ...] = ()
    denied: bool = False
    input_schema: dict[str, Any] = field(default_factory=dict)
    # Friendly name shown in the GUI (e.g. "Checked the date & time").
    # Optional. If empty, the GUI prettifies the tool_id.
    display_name: str = ""


class ToolContract(ABC):
    """
    Every tool must implement this interface. Nothing else.
    """

    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        ...

    @abstractmethod
    def execute(self, request: ToolRequest) -> ToolResult:
        """
        Perform the operation. MUST NOT raise for expected failures —
        return ToolResult.failure(...) instead.
        """
        ...

    @abstractmethod
    def verify(self, request: ToolRequest, result: ToolResult) -> bool:
        """
        Independently confirm the effect happened (spec §33, §94).
        Return True only with sufficient evidence.
        """
        ...

    def rollback(self, request: ToolRequest, result: ToolResult) -> None:
        """
        Optional compensating action. Default: no-op.
        """
        return None


class ToolRegistry:
    """
    Immutable after `seal()`. Discovery populates the registry; the
    agent only reads.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolContract] = {}
        self._sealed = False

    def register(self, tool: ToolContract) -> None:
        if self._sealed:
            raise RuntimeError("registry is sealed; cannot register after seal")
        tool_id = tool.spec.tool_id
        if tool_id in self._tools:
            raise ValueError(f"duplicate tool_id: {tool_id!r}")
        self._tools[tool_id] = tool

    def seal(self) -> None:
        self._sealed = True

    def has(self, tool_id: str) -> bool:
        return tool_id in self._tools

    def get(self, tool_id: str) -> Optional[ToolContract]:
        return self._tools.get(tool_id)

    def require(self, tool_id: str) -> ToolContract:
        tool = self._tools.get(tool_id)
        if tool is None:
            raise KeyError(f"unknown tool_id: {tool_id!r}")
        return tool

    def list_specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def tool_ids(self) -> list[str]:
        return sorted(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, tool_id: object) -> bool:
        return isinstance(tool_id, str) and tool_id in self._tools