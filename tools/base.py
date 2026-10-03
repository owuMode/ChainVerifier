# tools/base.py
"""
Tool models shared across the registry and every tool implementation.

Rules (spec §21, §23):
  * ToolRequest and ToolResult are the ONLY internal shapes.
  * Provider-specific or tool-specific formats never leak past this file.
  * Every tool returns a ToolResult, never raises past its boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class ToolRequest:
    """A validated, permission-checked request to execute a tool."""
    tool_id: str
    arguments: dict[str, Any]
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    dry_run: bool = False

    def __post_init__(self) -> None:
        if not self.tool_id:
            raise ValueError("tool_id must not be empty")
        if not isinstance(self.arguments, dict):
            raise TypeError("arguments must be a dict")


@dataclass
class ToolResult:
    """
    The outcome of a tool execution.

    `ok` is only True when the tool's own execute() reported success.
    It is NOT the same as "verified". The Verifier decides that.
    """
    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    error_code: Optional[str] = None

    # ---------------------------------------------------------------
    @classmethod
    def success(cls, output: Optional[dict[str, Any]] = None) -> "ToolResult":
        return cls(ok=True, output=output or {})

    @classmethod
    def failure(
        cls,
        error: str,
        *,
        error_code: Optional[str] = None,
        output: Optional[dict[str, Any]] = None,
    ) -> "ToolResult":
        return cls(
            ok=False,
            output=output or {},
            error=error,
            error_code=error_code,
        )