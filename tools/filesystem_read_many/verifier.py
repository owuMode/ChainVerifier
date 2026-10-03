# tools/filesystem_read_many/verifier.py
"""
Standalone verifier for filesystem_read_many.
Delegates to the tool's own verify().
"""

from __future__ import annotations

from tools.base import ToolRequest, ToolResult


def verify(request: ToolRequest, result: ToolResult) -> bool:
    from tools.filesystem_read_many.tool import TOOL
    return TOOL.verify(request, result)