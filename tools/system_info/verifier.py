# tools/system_info/verifier.py
"""
Standalone verifier for system_info.

Delegates to the tool's own verify(), which independently recomputes
the machine facts and compares them field-by-field.
"""

from __future__ import annotations

from tools.base import ToolRequest, ToolResult


def verify(request: ToolRequest, result: ToolResult) -> bool:
    from tools.system_info.tool import TOOL
    return TOOL.verify(request, result)