# gui/web/tasks_bridge.py
"""
TasksBridge — Python <-> JS boundary for the tasks page.

Responsibilities:
  * List recent tasks (with status filter).
  * Get full task detail: metadata, plan, audit trail (events).
  * Cancel a running task.
  * Retry a task (create a new task with the same goal).
  * Delete a terminal task from history.

Design:
  * No business logic here. Delegates to TaskManager, TaskRepository,
    AuditRepository, and (for retry) AgentWorker.
  * All responses are JSON strings — keeps QWebChannel marshalling simple.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal, Slot

from applog.logger import get_logger
from core.tasks.models import Task

log = get_logger("gui.web.tasks_bridge")


class TasksBridge(QObject):
    """
    Registered with QWebChannel as `tasksbridge`.
    """

    # Emitted when a task list or a task's state changes so JS can refresh.
    tasksChanged = Signal()

    # Emitted when a retry has been kicked off (carries the new task_id).
    retryStarted = Signal(str)

    def __init__(
        self,
        *,
        tasks,
        task_repo,
        audit_repo,
        agent,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._tasks = tasks
        self._task_repo = task_repo
        self._audit = audit_repo
        self._agent = agent
        self._retry_workers: list = []

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------
    @Slot(str, result=str)
    def listTasksJson(self, filter_kind: str) -> str:
        """
        Return tasks as a JSON string.

        filter_kind:
          "all"       — most recent 100 tasks
          "active"    — non-terminal tasks
          "completed" — COMPLETED only
          "failed"    — FAILED or CANCELLED
        """
        try:
            if filter_kind == "active":
                rows = self._task_repo.list_active()
            else:
                rows = self._task_repo.list_recent(limit=100)
        except Exception:
            log.exception("listTasksJson failed", extra={"filter": filter_kind})
            return "[]"

        if filter_kind == "completed":
            rows = [t for t in rows if t.status == "COMPLETED"]
        elif filter_kind == "failed":
            rows = [t for t in rows if t.status in ("FAILED", "CANCELLED")]

        payload = [_task_summary(t) for t in rows]
        return json.dumps(payload, ensure_ascii=False)

    @Slot(str, result=str)
    def getTaskJson(self, task_id: str) -> str:
        """
        Return a single task with its plan and audit trail.

        Shape:
          {
            "task": { ... summary + plan ... },
            "events": [ {event_type, created_at, actor, payload}, ... ]
          }
        """
        try:
            task = self._task_repo.get(task_id)
        except Exception:
            log.exception("getTaskJson: task lookup failed", extra={"task_id": task_id})
            return "{}"

        if task is None:
            return "{}"

        try:
            events = self._audit.by_task(task_id, limit=500)
        except Exception:
            log.exception("getTaskJson: audit lookup failed", extra={"task_id": task_id})
            events = []

        payload = {
            "task": _task_detail(task),
            "events": [_event_summary(e) for e in events],
        }
        return json.dumps(payload, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    @Slot(str, result=bool)
    def cancelTask(self, task_id: str) -> bool:
        try:
            task = self._task_repo.get(task_id)
        except Exception:
            log.exception("cancelTask: lookup failed", extra={"task_id": task_id})
            return False
        if task is None or task.is_terminal():
            return False
        try:
            self._tasks.request_cancel(task_id)
        except Exception:
            log.exception("cancelTask: request_cancel failed", extra={"task_id": task_id})
            return False
        self.tasksChanged.emit()
        log.info("task cancel requested from GUI", extra={"task_id": task_id})
        return True

    @Slot(str, result=str)
    def retryTask(self, task_id: str) -> str:
        """
        Create a new task with the same goal and start an agent run.

        Returns the new task_id on success, or empty string on failure.
        """
        try:
            original = self._task_repo.get(task_id)
        except Exception:
            log.exception("retryTask: lookup failed", extra={"task_id": task_id})
            return ""

        if original is None:
            return ""

        if self._agent is None or self._tasks is None:
            log.warning("retryTask: agent not configured")
            return ""

        from gui.web.agent_worker import AgentWorker

        try:
            new_task = self._tasks.create(
                original.goal,
                conversation_id=original.conversation_id,
                max_steps=original.max_steps,
                max_retries=original.max_retries,
                max_model_calls=original.max_model_calls,
                max_execution_time_s=original.max_execution_time_s,
            )
        except Exception:
            log.exception("retryTask: create failed")
            return ""

        worker = AgentWorker(
            agent=self._agent,
            tasks=self._tasks,
            goal=original.goal,
            conversation_id=original.conversation_id,
            max_steps=original.max_steps,
            max_retries=original.max_retries,
            max_model_calls=original.max_model_calls,
            max_execution_time_s=original.max_execution_time_s,
        )
        self._retry_workers.append(worker)
        worker.finished.connect(lambda: self._forget_worker(worker))
        worker.taskCreated.connect(lambda _tid: self.tasksChanged.emit())
        worker.start()

        self.retryStarted.emit(new_task.task_id)
        self.tasksChanged.emit()
        log.info(
            "task retry started from GUI",
            extra={"original": task_id, "new": new_task.task_id},
        )
        return new_task.task_id

    @Slot(str, result=bool)
    def deleteTask(self, task_id: str) -> bool:
        """
        Delete a task from history.

        Refuses to delete non-terminal tasks (cancel them first).
        """
        try:
            task = self._task_repo.get(task_id)
        except Exception:
            log.exception("deleteTask: lookup failed", extra={"task_id": task_id})
            return False

        if task is None:
            return False

        if not task.is_terminal():
            log.warning("deleteTask: task is not terminal", extra={"task_id": task_id})
            return False

        try:
            with self._task_repo._db.transaction() as conn:
                conn.execute("DELETE FROM tasks WHERE task_id = ?;", (task_id,))
        except Exception:
            log.exception("deleteTask: SQL failed", extra={"task_id": task_id})
            return False

        self.tasksChanged.emit()
        log.info("task deleted from GUI", extra={"task_id": task_id})
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _forget_worker(self, worker) -> None:
        try:
            self._retry_workers.remove(worker)
        except ValueError:
            pass


def _task_summary(task: Task) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "goal": task.goal,
        "status": task.status,
        "current_step": task.current_step,
        "max_steps": task.max_steps,
        "retry_count": task.retry_count,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
        "error": task.error,
        "conversation_id": task.conversation_id,
    }


def _task_detail(task: Task) -> dict[str, Any]:
    summary = _task_summary(task)
    summary["plan"] = task.plan or []
    summary["result"] = task.result
    return summary


def _event_summary(event) -> dict[str, Any]:
    return {
        "event_type": event.event_type,
        "created_at": event.created_at,
        "actor": event.actor,
        "payload": event.payload,
    }