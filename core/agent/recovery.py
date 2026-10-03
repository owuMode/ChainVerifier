# core/agent/recovery.py
"""
Recovery — decide whether to retry, replan, or fail (spec §30, §31).

Phase 3: adds REPLAN.
  * RETRY_SAME_STEP — retry the failed step (transient errors).
  * REPLAN          — ask the planner for a fresh plan (permanent
                      errors where the plan itself may be wrong).
  * FAIL            — give up.

The Agent decides whether replanning is worth the extra API call.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.agent.policies import AgentPolicy, FailureKind
from core.tasks.models import Task


class RecoveryAction(str, Enum):
    RETRY_SAME_STEP = "retry_same_step"
    REPLAN = "replan"
    FAIL = "fail"


@dataclass(frozen=True)
class RecoveryDecision:
    action: RecoveryAction
    reason: str


class Recovery:
    """
    Decides the recovery action for a failed step.

    Note: the actual replan attempt is capped by the agent
    (MAX_REPLANS_PER_TASK), not by this class.
    """

    def __init__(self, *, max_replans: int = 2) -> None:
        self._max_replans = int(max_replans)

    def decide(
        self,
        *,
        task: Task,
        error_code: str | None,
        error_message: str | None,
        replans_so_far: int = 0,
    ) -> RecoveryDecision:
        kind = AgentPolicy.classify_failure(error_code, error_message)

        # Permanent failure: the plan itself is likely wrong. Replan
        # if we still have budget.
        if kind is FailureKind.PERMANENT:
            if replans_so_far < self._max_replans:
                return RecoveryDecision(
                    RecoveryAction.REPLAN,
                    f"permanent failure ({error_code or 'unknown'}); replanning",
                )
            return RecoveryDecision(
                RecoveryAction.FAIL,
                f"permanent failure, no replans left "
                f"({replans_so_far}/{self._max_replans})",
            )

        # Transient / unknown: retry the same step if retries remain.
        if AgentPolicy.can_retry(task):
            return RecoveryDecision(
                RecoveryAction.RETRY_SAME_STEP,
                f"retryable ({kind.value})",
            )

        # Retries exhausted — try one replan if we have budget.
        if replans_so_far < self._max_replans:
            return RecoveryDecision(
                RecoveryAction.REPLAN,
                f"retries exhausted ({task.retry_count}/{task.max_retries}); "
                f"replanning",
            )

        return RecoveryDecision(
            RecoveryAction.FAIL,
            f"no retries or replans left "
            f"(retries={task.retry_count}/{task.max_retries}, "
            f"replans={replans_so_far}/{self._max_replans})",
        )