# tools/filesystem/verifier.py
"""
Standalone verifier for filesystem.

Delegates to the tool's own verify(), which re-reads the folder or
file independently.
"""

from __future__ import annotations

from tools.base import ToolRequest, ToolResult


def verify(request: ToolRequest, result: ToolResult) -> bool:
    from tools.filesystem.tool import TOOL
    return TOOL.verify(request, result)