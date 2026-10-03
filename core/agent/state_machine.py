# core/agent/state_machine.py
"""
Task state machine (spec §27).

States:
    CREATED
    UNDERSTANDING
    PLANNING
    WAITING_PERMISSION
    EXECUTING
    OBSERVING
    VERIFYING
    RECOVERING
    COMPLETED
    FAILED
    CANCELLED

Rules:
  * Every transition is explicit. Invalid transitions raise.
  * Terminal states cannot be left.
  * CANCELLED and FAILED are reachable from any non-terminal state.
  * COMPLETED is reachable only from VERIFYING (spec §33, §94).

Multi-step success bridge:
  `VERIFYING → EXECUTING` is legal. Without it, a task could not
  proceed from a successfully-verified step N to step N+1, because
  VERIFYING is otherwise a pre-terminal state. This transition does
  NOT shortcut completion: COMPLETED is still only reachable from
  VERIFYING after the last step.
"""

from __future__ import annotations

from enum import Enum


class TaskState(str, Enum):
    CREATED = "CREATED"
    UNDERSTANDING = "UNDERSTANDING"
    PLANNING = "PLANNING"
    WAITING_PERMISSION = "WAITING_PERMISSION"
    EXECUTING = "EXECUTING"
    OBSERVING = "OBSERVING"
    VERIFYING = "VERIFYING"
    RECOVERING = "RECOVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = frozenset({
    TaskState.COMPLETED,
    TaskState.FAILED,
    TaskState.CANCELLED,
})


# Transition table — source state -> allowed target states.
_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.CREATED: frozenset({
        TaskState.UNDERSTANDING,
        TaskState.CANCELLED,
        TaskState.FAILED,
    }),
    TaskState.UNDERSTANDING: frozenset({
        TaskState.PLANNING,
        TaskState.RECOVERING,
        TaskState.FAILED,
        TaskState.CANCELLED,
    }),
    TaskState.PLANNING: frozenset({
        TaskState.WAITING_PERMISSION,
        TaskState.EXECUTING,
        TaskState.RECOVERING,
        TaskState.FAILED,
        TaskState.CANCELLED,
    }),
    TaskState.WAITING_PERMISSION: frozenset({
        TaskState.EXECUTING,
        TaskState.PLANNING,
        TaskState.RECOVERING,
        TaskState.FAILED,
        TaskState.CANCELLED,
    }),
    TaskState.EXECUTING: frozenset({
        TaskState.OBSERVING,
        TaskState.RECOVERING,
        TaskState.FAILED,
        TaskState.CANCELLED,
    }),
    TaskState.OBSERVING: frozenset({
        TaskState.VERIFYING,
        TaskState.RECOVERING,
        TaskState.FAILED,
        TaskState.CANCELLED,
    }),
    # VERIFYING → EXECUTING: multi-step success bridge (see docstring).
    # COMPLETED remains reachable ONLY from VERIFYING.
    TaskState.VERIFYING: frozenset({
        TaskState.EXECUTING,
        TaskState.COMPLETED,
        TaskState.RECOVERING,
        TaskState.FAILED,
        TaskState.CANCELLED,
    }),
    TaskState.RECOVERING: frozenset({
        TaskState.UNDERSTANDING,
        TaskState.PLANNING,
        TaskState.EXECUTING,
        TaskState.FAILED,
        TaskState.CANCELLED,
    }),
    # Terminal — no outgoing edges.
    TaskState.COMPLETED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.CANCELLED: frozenset(),
}


class InvalidTransition(Exception):
    def __init__(self, source: TaskState, target: TaskState) -> None:
        super().__init__(f"invalid task transition: {source.value} -> {target.value}")
        self.source = source
        self.target = target


def is_terminal(state: TaskState) -> bool:
    return state in TERMINAL_STATES


def can_transition(source: TaskState, target: TaskState) -> bool:
    return target in _TRANSITIONS.get(source, frozenset())


def assert_transition(source: TaskState, target: TaskState) -> None:
    if not can_transition(source, target):
        raise InvalidTransition(source, target)


def allowed_targets(state: TaskState) -> frozenset[TaskState]:
    return _TRANSITIONS.get(state, frozenset())