# core/tasks/manager.py
"""
TaskManager — orchestration layer for tasks.

Responsibilities (spec §27, §31, §32):
  * Create tasks (validate limits, publish TASK_CREATED)
  * Apply state transitions (validate via state_machine, publish events)
  * Cancel tasks (flag + state transition, publish TASK_CANCELLED)
  * Persist on every change (single source of truth)

Lifecycle fields (status, error, timestamps) go through transition().
Non-lifecycle fields (plan, current_step, retry_count) go through
update_plan(). No other mutation path exists.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

from applog.logger import get_logger
from core.agent.state_machine import (
    InvalidTransition,
    TaskState,
    assert_transition,
    is_terminal,
)
from core.events.bus import EventBus
from core.events.events import EventType
from core.tasks.models import Task
from core.tasks.repository import TaskRepository

log = get_logger("core.tasks.manager")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskManager:
    def __init__(self, repo: TaskRepository, bus: EventBus) -> None:
        self._repo = repo
        self._bus = bus
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------
    def create(
        self,
        goal: str,
        *,
        conversation_id: Optional[str] = None,
        max_steps: int = 25,
        max_retries: int = 3,
        max_model_calls: int = 40,
        max_execution_time_s: int = 600,
    ) -> Task:
        if not goal.strip():
            raise ValueError("task goal must not be empty")

        task = Task(
            task_id="",
            status=TaskState.CREATED.value,
            goal=goal.strip(),
            conversation_id=conversation_id,
            max_steps=max_steps,
            max_retries=max_retries,
            max_model_calls=max_model_calls,
            max_execution_time_s=max_execution_time_s,
        )
        self._repo.create(task)

        self._bus.publish(
            EventType.TASK_CREATED,
            task_id=task.task_id,
            actor="system",
            payload={"goal": task.goal, "conversation_id": conversation_id},
        )
        return task

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def get(self, task_id: str) -> Optional[Task]:
        return self._repo.get(task_id)

    def list_recent(self, limit: int = 50) -> list[Task]:
        return self._repo.list_recent(limit=limit)

    def list_active(self) -> list[Task]:
        return self._repo.list_active()

    # ------------------------------------------------------------------
    # Non-lifecycle mutation
    # ------------------------------------------------------------------
    def update_plan(self, task: Task) -> None:
        """
        Persist non-lifecycle fields (plan, current_step, retry_count).

        The ONLY sanctioned way to mutate non-lifecycle state.
        Lifecycle (status, error, timestamps) goes through transition().
        """
        self._repo.update(task)

    # ------------------------------------------------------------------
    # Lifecycle transition
    # ------------------------------------------------------------------
    def transition(
        self,
        task_id: str,
        target: TaskState,
        *,
        error: Optional[str] = None,
    ) -> Task:
        with self._lock:
            task = self._repo.get(task_id)
            if task is None:
                raise ValueError(f"unknown task_id: {task_id!r}")

            source = TaskState(task.status)
            assert_transition(source, target)

            # Cancel flag governs: once set, only CANCELLED is reachable.
            if task.cancel_requested and target is not TaskState.CANCELLED:
                raise InvalidTransition(source, target)

            task.status = target.value
            if target is TaskState.EXECUTING and task.started_at is None:
                task.started_at = _utc_now()
            if target in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
                task.completed_at = _utc_now()
            if error is not None:
                task.error = error
            self._repo.update(task)

        # Publish after commit — never inside the lock, never before.
        self._publish_state_change(task, source, target)
        return task

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------
    def request_cancel(self, task_id: str) -> Task:
        with self._lock:
            task = self._repo.get(task_id)
            if task is None:
                raise ValueError(f"unknown task_id: {task_id!r}")

            if is_terminal(TaskState(task.status)):
                return task

            task.cancel_requested = True
            self._repo.update(task)

        self._bus.publish(
            EventType.TASK_UPDATED,
            task_id=task.task_id,
            actor="user",
            payload={"cancel_requested": True},
        )
        return task

    def mark_cancelled(self, task_id: str) -> Task:
        return self.transition(task_id, TaskState.CANCELLED)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _publish_state_change(
        self,
        task: Task,
        source: TaskState,
        target: TaskState,
    ) -> None:
        payload = {
            "from": source.value,
            "to": target.value,
            "error": task.error,
        }
        self._bus.publish(
            EventType.TASK_STATE_CHANGED,
            task_id=task.task_id,
            actor="system",
            payload=payload,
        )

        terminal_event = {
            TaskState.COMPLETED: EventType.TASK_COMPLETED,
            TaskState.FAILED: EventType.TASK_FAILED,
            TaskState.CANCELLED: EventType.TASK_CANCELLED,
        }.get(target)
        if terminal_event is not None:
            self._bus.publish(
                terminal_event,
                task_id=task.task_id,
                actor="system",
                payload={"error": task.error, "result": task.result},
            )