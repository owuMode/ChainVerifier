# core/services/mode.py
"""
Operation mode — how the assistant should respond to a user message.

Three modes:
  * CHAT   — answer directly, no tools
  * AGENT  — plan and execute tools
  * AUTO   — decide per-message using the classifier

Mode is persisted in ConfigurationService under `agent.mode`. It can
be changed by the user at any time (dropdown in the top bar) or by
the assistant itself if the user asks to switch.
"""

from __future__ import annotations

from enum import Enum


class Mode(str, Enum):
    CHAT = "chat"
    AGENT = "agent"
    AUTO = "auto"

    @classmethod
    def from_str(cls, value: str) -> "Mode":
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.AUTO


_DEFAULT_KEY = "agent.mode"


class ModeService:
    """Thin wrapper around ConfigurationService for the current mode."""

    def __init__(self, config) -> None:
        self._config = config

    def get(self) -> Mode:
        return Mode.from_str(str(self._config.get(_DEFAULT_KEY, "auto")))

    def set(self, mode: Mode) -> None:
        self._config.set(_DEFAULT_KEY, mode.value)