# tools/filesystem_write/verifier.py
"""
Standalone verifier for filesystem_write.

Delegates to the tool's own verify().
"""

from __future__ import annotations

from tools.base import ToolRequest, ToolResult


def verify(request: ToolRequest, result: ToolResult) -> bool:
    from tools.filesystem_write.tool import TOOL
    return TOOL.verify(request, result)