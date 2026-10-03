# core/agent/executor.py
"""
Executor — runs one step through the full tool pipeline.

Thread safety:
  * This class is stateless. Each call to execute_step() creates its
    own ToolRequest and ToolResult. It is safe to call from multiple
    threads simultaneously.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from applog.logger import get_logger
from core.agent.policies import AgentPolicy
from core.events.bus import EventBus
from core.events.events import EventType
from providers.base.capabilities import Capability
from providers.base.provider import AIProvider  # noqa: F401
from security.permissions import PermissionLevel
from security.policies import PolicyDecision, PolicyEngine
from security.validation import validate
from tools.base import ToolRequest, ToolResult
from tools.registry.registry import ToolRegistry

log = get_logger("core.agent.executor")


@dataclass
class StepOutcome:
    ok: bool
    result: ToolResult | None
    request: ToolRequest | None
    error: str | None = None
    error_code: str | None = None
    denied: bool = False


class Executor:
    def __init__(
        self,
        registry: ToolRegistry,
        policy_engine: PolicyEngine,
        event_bus: EventBus,
        permission_broker=None,
    ) -> None:
        self._registry = registry
        self._policy = policy_engine
        self._bus = event_bus
        self._broker = permission_broker

    # ------------------------------------------------------------------
    def execute_step(
        self,
        *,
        tool_id: str,
        arguments: dict,
        task_id: str,
        session_id: str | None = None,
        dry_run: bool = False,
        step_index: int | None = None,
    ) -> StepOutcome:
        # 1. Tool lookup
        tool = self._registry.get(tool_id)
        if tool is None:
            return StepOutcome(
                ok=False, result=None, request=None,
                error=f"unknown tool: {tool_id}",
                error_code="unknown_tool",
            )

        # 2. Schema validation
        errors = validate(tool.spec.input_schema, arguments)
        if errors:
            self._bus.publish(
                EventType.TOOL_FAILED,
                task_id=task_id,
                session_id=session_id,
                actor="agent",
                payload={
                    "tool_id": tool_id,
                    "step_index": step_index,
                    "display_name": tool.spec.display_name or tool_id,
                    "reason": "validation",
                    "errors": errors[:5],
                },
            )
            return StepOutcome(
                ok=False, result=None, request=None,
                error="; ".join(errors[:3]),
                error_code="validation_error",
            )

        # 3. Policy check
        verdict = self._policy.evaluate(
            permission_level=tool.spec.permission_level,
            tool_id=tool_id,
            manifest_denied=tool.spec.denied,
            dry_run=dry_run,
        )

        # 3a. DENY.
        if verdict.decision is PolicyDecision.DENY:
            self._bus.publish(
                EventType.TOOL_FAILED,
                task_id=task_id,
                session_id=session_id,
                actor="agent",
                payload={
                    "tool_id": tool_id,
                    "step_index": step_index,
                    "display_name": tool.spec.display_name or tool_id,
                    "reason": "denied",
                    "detail": verdict.reason,
                },
            )
            return StepOutcome(
                ok=False, result=None, request=None,
                error=verdict.reason,
                error_code="policy_denied",
                denied=True,
            )

        # 3b. REQUIRE_CONFIRM.
        if verdict.decision is PolicyDecision.REQUIRE_CONFIRM:
            decision = self._ask_permission(
                task_id=task_id,
                tool_id=tool_id,
                tool_display_name=tool.spec.display_name or tool_id,
                reason=verdict.reason,
                permission_level=tool.spec.permission_level.label(),
                arguments=arguments,
                conversation_id=session_id,
            )
            if decision == "deny":
                self._bus.publish(
                    EventType.TOOL_FAILED,
                    task_id=task_id,
                    session_id=session_id,
                    actor="user",
                    payload={
                        "tool_id": tool_id,
                        "step_index": step_index,
                        "display_name": tool.spec.display_name or tool_id,
                        "reason": "user_denied",
                    },
                )
                return StepOutcome(
                    ok=False, result=None, request=None,
                    error="User denied permission.",
                    error_code="user_denied",
                    denied=True,
                )

        # 4. Publish start
        request = ToolRequest(
            tool_id=tool_id,
            arguments=arguments,
            task_id=task_id,
            session_id=session_id,
            dry_run=dry_run,
        )
        self._bus.publish(
            EventType.TOOL_STARTED,
            task_id=task_id,
            session_id=session_id,
            actor="agent",
            payload={
                "tool_id": tool_id,
                "step_index": step_index,
                "display_name": tool.spec.display_name or tool_id,
                "arguments": dict(arguments),
            },
        )

        # 5. Execute
        try:
            result = tool.execute(request)
        except Exception as exc:
            log.exception("tool.execute raised", extra={"tool_id": tool_id})
            result = ToolResult.failure(
                f"{type(exc).__name__}: {exc}",
                error_code="tool_exception",
            )

        # 6. Publish result
        if result.ok:
            self._bus.publish(
                EventType.TOOL_COMPLETED,
                task_id=task_id,
                session_id=session_id,
                actor="agent",
                payload={
                    "tool_id": tool_id,
                    "step_index": step_index,
                    "display_name": tool.spec.display_name or tool_id,
                    "output": dict(result.output) if result.output else {},
                },
            )
        else:
            self._bus.publish(
                EventType.TOOL_FAILED,
                task_id=task_id,
                session_id=session_id,
                actor="agent",
                payload={
                    "tool_id": tool_id,
                    "step_index": step_index,
                    "display_name": tool.spec.display_name or tool_id,
                    "error": result.error,
                    "error_code": result.error_code,
                },
            )

        if not result.ok:
            return StepOutcome(
                ok=False, result=result, request=request,
                error=result.error,
                error_code=result.error_code or "tool_failed",
            )

        return StepOutcome(ok=True, result=result, request=request)

    # ------------------------------------------------------------------
    def _ask_permission(
        self,
        *,
        task_id: str,
        tool_id: str,
        tool_display_name: str,
        reason: str,
        permission_level: str,
        arguments: dict,
        conversation_id: str | None = None,
    ) -> str:
        if self._broker is None:
            log.warning("no permission broker; soft-denying", extra={"tool_id": tool_id})
            return "deny"
        try:
            decision = self._broker.request(
                task_id=task_id,
                tool_id=tool_id,
                tool_display_name=tool_display_name,
                reason=reason,
                permission_level=permission_level,
                arguments=dict(arguments or {}),
                conversation_id=conversation_id,
            )
            value = getattr(decision, "value", str(decision))
            return "allow" if value in ("allow", "always", "allow_chat") else "deny"
        except Exception:
            log.exception("permission broker raised; denying")
            return "deny"