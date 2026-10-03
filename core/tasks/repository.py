# core/tasks/repository.py
"""
TaskRepository — persistence for `tasks` (spec §28, §36).

All SQL for `tasks` lives here. Nothing else touches the table.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from core.tasks.models import Task
from database.manager import DatabaseManager


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    def create(self, task: Task) -> Task:
        if not task.task_id:
            task.task_id = str(uuid.uuid4())
        now = _utc_now()
        task.created_at = task.created_at or now
        task.updated_at = now
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO tasks
                    (task_id, conversation_id, status, goal, plan, current_step,
                     result, error, retry_count, max_retries, max_steps,
                     max_model_calls, max_execution_time_s,
                     created_at, updated_at, started_at, completed_at,
                     cancel_requested)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    task.task_id,
                    task.conversation_id,
                    task.status,
                    task.goal,
                    json.dumps(task.plan, ensure_ascii=False),
                    task.current_step,
                    task.result,
                    task.error,
                    task.retry_count,
                    task.max_retries,
                    task.max_steps,
                    task.max_model_calls,
                    task.max_execution_time_s,
                    task.created_at,
                    task.updated_at,
                    task.started_at,
                    task.completed_at,
                    1 if task.cancel_requested else 0,
                ),
            )
        return task

    def update(self, task: Task) -> None:
        task.updated_at = _utc_now()
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE tasks SET
                    conversation_id = ?,
                    status = ?,
                    goal = ?,
                    plan = ?,
                    current_step = ?,
                    result = ?,
                    error = ?,
                    retry_count = ?,
                    max_retries = ?,
                    max_steps = ?,
                    max_model_calls = ?,
                    max_execution_time_s = ?,
                    updated_at = ?,
                    started_at = ?,
                    completed_at = ?,
                    cancel_requested = ?
                WHERE task_id = ?;
                """,
                (
                    task.conversation_id,
                    task.status,
                    task.goal,
                    json.dumps(task.plan, ensure_ascii=False),
                    task.current_step,
                    task.result,
                    task.error,
                    task.retry_count,
                    task.max_retries,
                    task.max_steps,
                    task.max_model_calls,
                    task.max_execution_time_s,
                    task.updated_at,
                    task.started_at,
                    task.completed_at,
                    1 if task.cancel_requested else 0,
                    task.task_id,
                ),
            )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def get(self, task_id: str) -> Optional[Task]:
        row = self._db.connection.execute(
            "SELECT * FROM tasks WHERE task_id = ?;",
            (task_id,),
        ).fetchone()
        return _row_to_task(row) if row else None

    def list_recent(self, limit: int = 50) -> list[Task]:
        rows = self._db.connection.execute(
            "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?;",
            (limit,),
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def list_active(self) -> list[Task]:
        rows = self._db.connection.execute(
            """
            SELECT * FROM tasks
            WHERE status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED')
            ORDER BY updated_at DESC;
            """
        ).fetchall()
        return [_row_to_task(r) for r in rows]


# ----------------------------------------------------------------------
def _row_to_task(row) -> Task:
    try:
        plan_raw = json.loads(row["plan"]) if row["plan"] else []
    except json.JSONDecodeError:
        plan_raw = []
    return Task(
        task_id=row["task_id"],
        conversation_id=row["conversation_id"],
        status=row["status"],
        goal=row["goal"],
        plan=plan_raw if isinstance(plan_raw, list) else [],
        current_step=int(row["current_step"] or 0),
        result=row["result"],
        error=row["error"],
        retry_count=int(row["retry_count"] or 0),
        max_retries=int(row["max_retries"] or 3),
        max_steps=int(row["max_steps"] or 25),
        max_model_calls=int(row["max_model_calls"] or 40),
        max_execution_time_s=int(row["max_execution_time_s"] or 600),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        cancel_requested=bool(row["cancel_requested"]),
    )