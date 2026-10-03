# gui/web/chat_worker_types.py
"""
Small shared enum for the GUI worker mode.

Kept in its own file so workers and the bridge can import it without
pulling in Qt at module import time.
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