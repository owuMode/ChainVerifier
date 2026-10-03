# tests/integration/test_task_lifecycle.py
from pathlib import Path

import pytest

from core.agent.state_machine import InvalidTransition, TaskState
from core.events.bus import EventBus
from core.events.events import EventType
from core.tasks.manager import TaskManager
from core.tasks.repository import TaskRepository
from database.manager import DatabaseManager


def _migrations_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "database" / "migrations"


@pytest.fixture
def task_stack(tmp_path: Path):
    db = DatabaseManager(db_path=tmp_path / "app.sqlite", migrations_dir=_migrations_dir())
    db.open()
    bus = EventBus()
    repo = TaskRepository(db)
    manager = TaskManager(repo, bus)
    try:
        yield bus, manager, repo
    finally:
        db.close()


def test_task_lifecycle_persists_and_publishes(task_stack):
    bus, manager, repo = task_stack

    created: list[str] = []
    state_changes: list[dict] = []
    bus.subscribe(EventType.TASK_CREATED, lambda e: created.append(e.task_id))
    bus.subscribe(EventType.TASK_STATE_CHANGED, lambda e: state_changes.append(e.payload))

    task = manager.create("do a thing")
    assert task.task_id
    assert created == [task.task_id]

    manager.transition(task.task_id, TaskState.UNDERSTANDING)
    manager.transition(task.task_id, TaskState.PLANNING)
    manager.transition(task.task_id, TaskState.EXECUTING)
    manager.transition(task.task_id, TaskState.OBSERVING)
    manager.transition(task.task_id, TaskState.VERIFYING)
    final = manager.transition(task.task_id, TaskState.COMPLETED)

    assert final.status == TaskState.COMPLETED.value
    assert final.started_at is not None
    assert final.completed_at is not None

    # Persisted
    reloaded = repo.get(task.task_id)
    assert reloaded is not None
    assert reloaded.status == TaskState.COMPLETED.value

    # Events emitted for each hop
    assert [c["to"] for c in state_changes] == [
        "UNDERSTANDING",
        "PLANNING",
        "EXECUTING",
        "OBSERVING",
        "VERIFYING",
        "COMPLETED",
    ]


def test_invalid_transition_rejected(task_stack):
    _bus, manager, _repo = task_stack
    task = manager.create("x")
    with pytest.raises(InvalidTransition):
        manager.transition(task.task_id, TaskState.COMPLETED)


def test_cancel_flag_forces_cancelled(task_stack):
    _bus, manager, repo = task_stack
    task = manager.create("x")
    manager.transition(task.task_id, TaskState.UNDERSTANDING)

    manager.request_cancel(task.task_id)
    # Any non-cancel target now rejected.
    with pytest.raises(InvalidTransition):
        manager.transition(task.task_id, TaskState.PLANNING)

    # Cancellation still allowed.
    cancelled = manager.mark_cancelled(task.task_id)
    assert cancelled.status == TaskState.CANCELLED.value

    reloaded = repo.get(task.task_id)
    assert reloaded.status == TaskState.CANCELLED.value
    assert reloaded.cancel_requested is True


def test_terminal_has_no_outgoing(task_stack):
    _bus, manager, _repo = task_stack
    task = manager.create("x")
    manager.transition(task.task_id, TaskState.UNDERSTANDING)
    manager.transition(task.task_id, TaskState.PLANNING)
    manager.transition(task.task_id, TaskState.EXECUTING)
    manager.transition(task.task_id, TaskState.OBSERVING)
    manager.transition(task.task_id, TaskState.VERIFYING)
    manager.transition(task.task_id, TaskState.COMPLETED)

    with pytest.raises(InvalidTransition):
        manager.transition(task.task_id, TaskState.EXECUTING)