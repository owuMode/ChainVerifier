# tools/datetime/verifier.py
"""
Standalone verifier for datetime.

The ToolContract already exposes verify(); this file exists so future
tools with more complex verification needs have a dedicated place.
For datetime the verifier simply delegates to the tool's own verify(),
which independently recomputes the expected fields.
"""

from __future__ import annotations

from tools.base import ToolRequest, ToolResult


def verify(request: ToolRequest, result: ToolResult) -> bool:
    from tools.datetime.tool import TOOL
    return TOOL.verify(request, result)