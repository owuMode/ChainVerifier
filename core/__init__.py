# core/__init__.py
"""
Core package.

Kept lazy on purpose: submodules (events, tasks, agent) import each
other in ways that are order-sensitive. Eager re-exports at the
package level would create a fragile import surface.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
    # events
    "EventBus": ("core.events.bus", "EventBus"),
    "Event": ("core.events.bus", "Event"),
    "EventType": ("core.events.events", "EventType"),
    # tasks
    "Task": ("core.tasks.models", "Task"),
    "TaskRepository": ("core.tasks.repository", "TaskRepository"),
    "TaskManager": ("core.tasks.manager", "TaskManager"),
    # state machine
    "TaskState": ("core.agent.state_machine", "TaskState"),
    "InvalidTransition": ("core.agent.state_machine", "InvalidTransition"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'core' has no attribute {name!r}")
    module_path, attr = target
    value = getattr(import_module(module_path), attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(_EXPORTS.keys())


__all__ = sorted(_EXPORTS.keys())