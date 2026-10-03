# gui/web/agent_worker.py
"""
AgentWorker — run a task through the Agent off the UI thread.

The worker:
  1. Creates a task via TaskManager.
  2. Runs Agent.run(task_id).
  3. Emits the final message (or error) back to the bridge.

Progress events (task created, step started, tool completed, synthesis
chunks, etc.) come from EventBus and are handled by TaskTracker.
"""

from __future__ import annotations

import threading
from typing import Optional

from PySide6.QtCore import QThread, Signal

from applog.logger import get_logger
from core.agent.state_machine import TaskState

log = get_logger("gui.web.agent_worker")


class AgentWorker(QThread):
    finishedOk = Signal(str)
    finishedErr = Signal(str)
    taskCreated = Signal(str)

    def __init__(
        self,
        *,
        agent,
        tasks,
        goal: str,
        conversation_id: Optional[str] = None,
        max_steps: int = 25,
        max_retries: int = 3,
        max_model_calls: int = 40,
        max_execution_time_s: int = 600,
        parent: Optional[QThread] = None,
    ) -> None:
        super().__init__(parent)
        self._agent = agent
        self._tasks = tasks
        self._goal = goal
        self._conversation_id = conversation_id
        self._max_steps = max_steps
        self._max_retries = max_retries
        self._max_model_calls = max_model_calls
        self._max_execution_time_s = max_execution_time_s
        self._cancel_event = threading.Event()
        self._task_id: Optional[str] = None

    def request_cancel(self) -> None:
        self._cancel_event.set()
        if self._task_id is not None:
            try:
                self._tasks.request_cancel(self._task_id)
            except Exception:
                log.exception("request_cancel failed", extra={"task_id": self._task_id})

    def run(self) -> None:
        if self._agent is None or self._tasks is None:
            self.finishedErr.emit(
                "Agent is not configured. Open Settings and add an API key."
            )
            return

        try:
            task = self._tasks.create(
                self._goal,
                conversation_id=self._conversation_id,
                max_steps=self._max_steps,
                max_retries=self._max_retries,
                max_model_calls=self._max_model_calls,
                max_execution_time_s=self._max_execution_time_s,
            )
        except Exception as exc:
            log.exception("AgentWorker: task creation failed")
            self.finishedErr.emit(f"Could not create task: {type(exc).__name__}")
            return

        self._task_id = task.task_id
        self.taskCreated.emit(task.task_id)

        if self._cancel_event.is_set():
            try:
                self._tasks.mark_cancelled(task.task_id)
            except Exception:
                log.exception("mark_cancelled failed")
            return

        try:
            result = self._agent.run(task.task_id)
        except Exception as exc:
            log.exception("AgentWorker: agent.run raised")
            self.finishedErr.emit(f"Agent crashed: {type(exc).__name__}: {exc}")
            return

        if result.final_state is TaskState.COMPLETED:
            msg = result.final_message or "Task completed."
            self.finishedOk.emit(msg)
            return

        if result.final_state is TaskState.CANCELLED:
            self.finishedErr.emit("Task cancelled.")
            return

        reason = result.error or result.final_message or "Task failed."
        self.finishedErr.emit(reason)