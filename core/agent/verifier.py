# core/agent/verifier.py
"""
Verifier — the ONLY source of truth about success (spec §33, §94).

Never treat `result.ok == True` as success. Always ask the tool's
verifier, which recomputes evidence independently.

If a tool does not have a verify implementation (it always does —
ToolContract requires it), the verifier fails the step. There is no
"assume success" path.
"""

from __future__ import annotations

from dataclasses import dataclass

from applog.logger import get_logger
from core.events.bus import EventBus
from core.events.events import EventType
from tools.base import ToolRequest, ToolResult
from tools.registry.registry import ToolRegistry

log = get_logger("core.agent.verifier")


@dataclass(frozen=True)
class VerificationOutcome:
    verified: bool
    reason: str = ""


class Verifier:
    def __init__(self, registry: ToolRegistry, event_bus: EventBus) -> None:
        self._registry = registry
        self._bus = event_bus

    def verify(
        self,
        *,
        tool_id: str,
        request: ToolRequest,
        result: ToolResult,
        task_id: str,
        session_id: str | None = None,
    ) -> VerificationOutcome:
        tool = self._registry.get(tool_id)
        if tool is None:
            return VerificationOutcome(False, "tool no longer registered")

        if not result.ok:
            # Nothing to verify — failed executions are verified=false.
            return VerificationOutcome(False, "execution did not succeed")

        try:
            verified = bool(tool.verify(request, result))
        except Exception as exc:
            log.exception("tool.verify raised", extra={"tool_id": tool_id})
            return VerificationOutcome(False, f"verifier raised: {type(exc).__name__}")

        # Publish the outcome so the GUI / audit bridge sees it.
        self._bus.publish(
            EventType.TASK_UPDATED,
            task_id=task_id,
            session_id=session_id,
            actor="agent",
            payload={
                "tool_id": tool_id,
                "verified": verified,
            },
        )

        return VerificationOutcome(
            verified=verified,
            reason="verified" if verified else "verification failed",
        )