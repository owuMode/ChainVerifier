# tools/system_info/tool.py
"""
system_info — report facts about the current machine.

Pure Python. Read-only. No side effects.

The verifier recomputes the values independently and compares them
with what was reported. Any mismatch (or missing marker) fails
verification.
"""

from __future__ import annotations

import platform
import socket
import sys
from typing import Any

from security.permissions import PermissionLevel
from tools.base import ToolRequest, ToolResult
from tools.registry.registry import ToolContract, ToolSpec


_INPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "system_info input",
    "description": "No arguments. Returns facts about the current machine.",
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


_SPEC = ToolSpec(
    tool_id="system_info",
    name="System Info",
    description=(
        "Reports basic facts about the current machine: operating "
        "system, version, architecture, Python version, host name."
    ),
    category="system",
    version="1.0.0",
    permission_level=PermissionLevel.SAFE,
    capabilities=("safe", "side_effect_free", "read_only"),
    denied=False,
    input_schema=_INPUT_SCHEMA,
    display_name="Checked system info",
)


def _detect_windows_display() -> str:
    """
    Return a human-readable Windows version.

    On Windows 11, `platform.release()` lies and returns "10". We use
    the build number to distinguish:
        * Windows 11 build numbers are >= 22000.
        * Windows 10 build numbers are < 22000 and >= 10240.

    Reference: Microsoft's official build ranges.
    """
    if platform.system().lower() != "windows":
        return platform.system()

    version_str = platform.version()  # e.g. "10.0.22631"
    parts = version_str.split(".")
    if len(parts) >= 3:
        try:
            build = int(parts[2])
        except ValueError:
            build = 0
        if build >= 22000:
            return "Windows 11"
        if build >= 10240:
            return "Windows 10"
    return "Windows"


def _collect() -> dict:
    os_display = _detect_windows_display()
    release = platform.release()
    version = platform.version()

    return {
        "os_name": platform.system(),
        "os_display_name": os_display,
        "os_release": release,
        "os_version": version,
        "architecture": platform.machine(),
        "processor": platform.processor() or "unknown",
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "hostname": socket.gethostname(),
        "is_windows": platform.system().lower() == "windows",
        "marker": "SYSTEM_INFO_OK",
    }


class SystemInfoTool(ToolContract):

    @property
    def spec(self) -> ToolSpec:
        return _SPEC

    # ------------------------------------------------------------------
    def execute(self, request: ToolRequest) -> ToolResult:
        return ToolResult.success(_collect())

    # ------------------------------------------------------------------
    def verify(self, request: ToolRequest, result: ToolResult) -> bool:
        if not result.ok:
            return False

        out = result.output
        if out.get("marker") != "SYSTEM_INFO_OK":
            return False

        expected = _collect()

        for key, value in expected.items():
            if key == "marker":
                continue
            if out.get(key) != value:
                return False

        return True

    # ------------------------------------------------------------------
    def rollback(self, request: ToolRequest, result: ToolResult) -> None:
        return None


TOOL: ToolContract = SystemInfoTool()