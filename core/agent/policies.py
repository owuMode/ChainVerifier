# core/agent/policies.py
"""
Agent policies — the agent's own limits (spec §31, §30).

These are DIFFERENT from security/policies.py:
  * security/policies.py decides whether a tool may run at all.
  * core/agent/policies.py decides how the agent itself behaves:
      - how many steps it may take
      - how many times it may retry a failed step
      - how many model calls it may make
      - how long it may run
      - whether a failure is retryable

Never hardcode any of these; they come from Task limits + config.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.tasks.models import Task


class FailureKind(str, Enum):
    TRANSIENT = "transient"          # retry is worth it (network, rate limit)
    PERMANENT = "permanent"          # retry will not help (invalid args, policy deny)
    UNKNOWN = "unknown"              # safest: no retry unless limit allows


@dataclass(frozen=True)
class AgentLimits:
    max_steps: int
    max_retries: int
    max_model_calls: int
    max_execution_time_s: int

    @classmethod
    def from_task(cls, task: Task) -> "AgentLimits":
        return cls(
            max_steps=task.max_steps,
            max_retries=task.max_retries,
            max_model_calls=task.max_model_calls,
            max_execution_time_s=task.max_execution_time_s,
        )


class AgentPolicy:
    """
    Pure decision functions. No side effects, no state.

    Callers pass in what they know; the policy returns a verdict.
    """

    # Permanent failures — retrying will NOT help.
    _PERMANENT_CODES = frozenset({
        "validation_error",
        "policy_denied",
        "permission_denied",
        "auth_error",
        "no_active_provider",
        "unknown_tool",
        "invalid_path",
        "unsupported_action",
        "not_found",
        "not_a_directory",
        "not_a_file",
        "binary_file",
        "file_too_large",
        "user_denied",
    })

    # Transient failures — retrying MIGHT help.
    _TRANSIENT_CODES = frozenset({
        "network_error",
        "rate_limit",
        "timeout",
        "server_error",
    })

    @staticmethod
    def can_start_step(task: Task) -> bool:
        return task.current_step < task.max_steps

    @staticmethod
    def can_retry(task: Task) -> bool:
        return task.retry_count < task.max_retries

    @staticmethod
    def can_call_model(model_calls_so_far: int, limit: AgentLimits) -> bool:
        return model_calls_so_far < limit.max_model_calls

    @staticmethod
    def classify_failure(error_code: str | None, error_message: str | None) -> FailureKind:
        """
        Classify a failure into TRANSIENT / PERMANENT / UNKNOWN.

        Conservative by design: unknown failures are NOT retried
        automatically unless the caller explicitly allows it.
        """
        if error_code is None and not error_message:
            return FailureKind.UNKNOWN

        code = (error_code or "").lower()
        msg = (error_message or "").lower()

        if code in AgentPolicy._PERMANENT_CODES:
            return FailureKind.PERMANENT

        if code in AgentPolicy._TRANSIENT_CODES:
            return FailureKind.TRANSIENT

        # Heuristic on the message (last resort).
        if any(tok in msg for tok in (
            "timeout",
            "connection reset",
            "temporarily unavailable",
            "server busy",
        )):
            return FailureKind.TRANSIENT

        if any(tok in msg for tok in (
            "invalid",
            "not allowed",
            "denied",
            "missing",
            "not found",
            "does not exist",
        )):
            return FailureKind.PERMANENT

        return FailureKind.UNKNOWN

    @staticmethod
    def should_retry(task: Task, failure: FailureKind) -> bool:
        if failure is FailureKind.PERMANENT:
            return False
        if failure is FailureKind.TRANSIENT:
            return AgentPolicy.can_retry(task)
        # UNKNOWN: retry only if retries are left.
        return AgentPolicy.can_retry(task)