# tools/datetime/tool.py
"""
datetime — return the current date and time.

Pure Python. No filesystem, no network, no OS mutation.

The verifier independently checks that the returned timestamp is
consistent with the wall clock at verification time (within a small
tolerance) and that the derived fields (date, time, day of week)
match the timestamp exactly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from security.permissions import PermissionLevel
from tools.base import ToolRequest, ToolResult
from tools.registry.registry import ToolContract, ToolSpec


_INPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "datetime input",
    "description": "No arguments. Returns the current date and time.",
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


_SPEC = ToolSpec(
    tool_id="datetime",
    name="Date & Time",
    description=(
        "Returns the current date, time, timezone, and day of week "
        "in the system's local timezone, plus the equivalent UTC time."
    ),
    category="system",
    version="1.0.0",
    permission_level=PermissionLevel.SAFE,
    capabilities=("safe", "side_effect_free", "read_only"),
    denied=False,
    input_schema=_INPUT_SCHEMA,
    display_name="Checked the date & time",
)


class DateTimeTool(ToolContract):

    @property
    def spec(self) -> ToolSpec:
        return _SPEC

    # ------------------------------------------------------------------
    def execute(self, request: ToolRequest) -> ToolResult:
        now_local = datetime.now().astimezone()
        now_utc = now_local.astimezone(timezone.utc)

        output = {
            "iso_local": now_local.isoformat(),
            "iso_utc": now_utc.isoformat(),
            "date": now_local.strftime("%Y-%m-%d"),
            "time": now_local.strftime("%H:%M:%S"),
            "day_of_week": now_local.strftime("%A"),
            "timezone_name": now_local.tzname() or "unknown",
            "utc_offset": now_local.strftime("%z"),
            "unix_timestamp": int(now_local.timestamp()),
            "marker": "DATETIME_OK",
        }
        return ToolResult.success(output)

    # ------------------------------------------------------------------
    def verify(self, request: ToolRequest, result: ToolResult) -> bool:
        if not result.ok:
            return False

        out = result.output
        if out.get("marker") != "DATETIME_OK":
            return False

        try:
            reported = datetime.fromisoformat(out["iso_local"])
        except (KeyError, ValueError):
            return False

        now = datetime.now().astimezone()
        delta = abs((now - reported).total_seconds())
        if delta > 60:
            return False

        if out.get("date") != reported.strftime("%Y-%m-%d"):
            return False
        if out.get("time") != reported.strftime("%H:%M:%S"):
            return False
        if out.get("day_of_week") != reported.strftime("%A"):
            return False

        return True

    # ------------------------------------------------------------------
    def rollback(self, request: ToolRequest, result: ToolResult) -> None:
        return None


TOOL: ToolContract = DateTimeTool()