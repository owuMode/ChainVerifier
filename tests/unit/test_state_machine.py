# tests/unit/test_state_machine.py
import pytest

from core.agent.state_machine import (
    InvalidTransition,
    TaskState,
    allowed_targets,
    assert_transition,
    can_transition,
    is_terminal,
)


def test_terminal_states_have_no_outgoing_edges():
    for state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
        assert allowed_targets(state) == frozenset()
        assert is_terminal(state)


def test_happy_path_is_valid():
    path = [
        TaskState.CREATED,
        TaskState.UNDERSTANDING,
        TaskState.PLANNING,
        TaskState.EXECUTING,
        TaskState.OBSERVING,
        TaskState.VERIFYING,
        TaskState.COMPLETED,
    ]
    for src, dst in zip(path, path[1:]):
        assert can_transition(src, dst)
        assert_transition(src, dst)


def test_completed_only_from_verifying():
    # Spec §33, §94 — never claim success without verification.
    for src in TaskState:
        if src is TaskState.VERIFYING:
            continue
        assert not can_transition(src, TaskState.COMPLETED), f"{src} -> COMPLETED should be invalid"


def test_cancellation_reachable_from_non_terminal():
    for src in TaskState:
        if is_terminal(src):
            continue
        assert can_transition(src, TaskState.CANCELLED), f"{src} -> CANCELLED should be allowed"


def test_invalid_transition_raises():
    with pytest.raises(InvalidTransition):
        assert_transition(TaskState.CREATED, TaskState.COMPLETED)

    with pytest.raises(InvalidTransition):
        assert_transition(TaskState.COMPLETED, TaskState.EXECUTING)

def test_verifying_to_executing_is_allowed_multistep_bridge():
    # Required by the agent's multi-step flow. VERIFYING → EXECUTING
    # lets a verified step N proceed to step N+1. It does NOT let the
    # task reach COMPLETED without a final VERIFYING → COMPLETED.
    assert can_transition(TaskState.VERIFYING, TaskState.EXECUTING)