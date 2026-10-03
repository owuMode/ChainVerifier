# core/tasks/models.py
"""
Task model (spec §28).

This is the durable representation of a unit of work the agent is
performing. It is NOT a conversation message. A conversation may
contain zero, one, or many tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Task:
    task_id: str
    status: str                          # state machine value
    goal: str
    conversation_id: Optional[str] = None
    plan: list[dict[str, Any]] = field(default_factory=list)
    current_step: int = 0
    result: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    max_steps: int = 25
    max_model_calls: int = 40
    max_execution_time_s: int = 600
    created_at: str = ""
    updated_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    cancel_requested: bool = False

    # ------------------------------------------------------------------
    # Introspection helpers (no persistence, no side effects)
    # ------------------------------------------------------------------
    def is_terminal(self) -> bool:
        return self.status in {"COMPLETED", "FAILED", "CANCELLED"}

    def is_active(self) -> bool:
        return not self.is_terminal()

    def has_retries_left(self) -> bool:
        return self.retry_count < self.max_retries

    def has_steps_left(self) -> bool:
        return self.current_step < self.max_steps