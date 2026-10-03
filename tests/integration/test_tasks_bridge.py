# tests/integration/test_tasks_bridge.py
"""
Smoke tests for TasksBridge.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture(scope="module", autouse=True)
def _offscreen_qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    yield


def _migrations_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "database" / "migrations"


@pytest.fixture
def stack(tmp_path: Path):
    from core.events.bus import EventBus
    from core.tasks.manager import TaskManager
    from core.tasks.repository import TaskRepository
    from database.manager import DatabaseManager
    from database.repositories.audit import AuditRepository

    db = DatabaseManager(
        db_path=tmp_path / "app.sqlite",
        migrations_dir=_migrations_dir(),
    )
    db.open()

    bus = EventBus()
    task_repo = TaskRepository(db)
    tasks = TaskManager(task_repo, bus)
    audit = AuditRepository(db)

    try:
        yield {
            "db": db,
            "bus": bus,
            "tasks": tasks,
            "task_repo": task_repo,
            "audit": audit,
        }
    finally:
        db.close()


@pytest.fixture
def bridge(stack):
    from gui.web.tasks_bridge import TasksBridge

    return TasksBridge(
        tasks=stack["tasks"],
        task_repo=stack["task_repo"],
        audit_repo=stack["audit"],
        agent=None,
    )


# ----------------------------------------------------------------------
def test_list_empty(bridge):
    assert bridge.listTasksJson("all") == "[]"


def test_list_returns_created_task(bridge, stack):
    t = stack["tasks"].create("hello task")
    raw = bridge.listTasksJson("all")
    rows = json.loads(raw)
    assert len(rows) == 1
    assert rows[0]["task_id"] == t.task_id
    assert rows[0]["goal"] == "hello task"
    assert rows[0]["status"] == "CREATED"


def test_get_task_detail(bridge, stack):
    t = stack["tasks"].create("detail task")
    raw = bridge.getTaskJson(t.task_id)
    data = json.loads(raw)
    assert data["task"]["task_id"] == t.task_id
    assert data["task"]["goal"] == "detail task"
    assert isinstance(data["events"], list)


def test_get_unknown_task_returns_empty(bridge):
    assert bridge.getTaskJson("nope") == "{}"


def test_cancel_terminal_task_returns_false(bridge, stack):
    t = stack["tasks"].create("term task")
    # Force it to FAILED so it is terminal.
    from core.agent.state_machine import TaskState
    stack["tasks"].transition(t.task_id, TaskState.UNDERSTANDING)
    stack["tasks"].transition(t.task_id, TaskState.FAILED, error="nope")

    assert bridge.cancelTask(t.task_id) is False


def test_cancel_running_task(bridge, stack):
    t = stack["tasks"].create("running task")
    from core.agent.state_machine import TaskState
    stack["tasks"].transition(t.task_id, TaskState.UNDERSTANDING)

    assert bridge.cancelTask(t.task_id) is True
    reloaded = stack["task_repo"].get(t.task_id)
    assert reloaded.cancel_requested is True


def test_filter_completed(bridge, stack):
    from core.agent.state_machine import TaskState

    # Create one completed task.
    t = stack["tasks"].create("completed task")
    stack["tasks"].transition(t.task_id, TaskState.UNDERSTANDING)
    stack["tasks"].transition(t.task_id, TaskState.PLANNING)
    stack["tasks"].transition(t.task_id, TaskState.EXECUTING)
    stack["tasks"].transition(t.task_id, TaskState.OBSERVING)
    stack["tasks"].transition(t.task_id, TaskState.VERIFYING)
    stack["tasks"].transition(t.task_id, TaskState.COMPLETED)

    # And a second, still running.
    stack["tasks"].create("pending task")

    rows = json.loads(bridge.listTasksJson("completed"))
    assert len(rows) == 1
    assert rows[0]["task_id"] == t.task_id


def test_filter_active(bridge, stack):
    stack["tasks"].create("active task")
    rows = json.loads(bridge.listTasksJson("active"))
    assert len(rows) == 1


def test_delete_terminal_task(bridge, stack):
    from core.agent.state_machine import TaskState

    t = stack["tasks"].create("to delete")
    stack["tasks"].transition(t.task_id, TaskState.UNDERSTANDING)
    stack["tasks"].transition(t.task_id, TaskState.FAILED, error="boom")

    assert bridge.deleteTask(t.task_id) is True
    assert stack["task_repo"].get(t.task_id) is None


def test_delete_active_task_refused(bridge, stack):
    t = stack["tasks"].create("active")
    stack["tasks"].transition(t.task_id, TaskState.UNDERSTANDING) \
        if False else None
    from core.agent.state_machine import TaskState
    stack["tasks"].transition(t.task_id, TaskState.UNDERSTANDING)

    assert bridge.deleteTask(t.task_id) is False
    assert stack["task_repo"].get(t.task_id) is not None


def test_retry_without_agent_returns_empty(bridge, stack):
    t = stack["tasks"].create("retry me")
    assert bridge.retryTask(t.task_id) == ""