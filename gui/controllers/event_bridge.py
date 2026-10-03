# gui/controllers/event_bridge.py
"""
EventBridge — forward selected backend events to the GUI.

Phase 1: this bridge is a placeholder. The only event that will be
forwarded in later phases is TASK_* (for agent runs). For pure chat,
the GuiBridge handles everything.

Kept as a separate file so the GUI can grow event-driven behaviour
without touching AppController.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject

from applog.logger import get_logger
from core.events.bus import EventBus
from core.events.events import EventType

log = get_logger("gui.controllers.events")


class EventBridge(QObject):
    """
    Subscribes to the EventBus and forwards a small allowlist of events
    to the GUI. Handlers must be fast and must never raise — the bus
    swallows exceptions but we still keep them clean.
    """

    _ALLOWED = frozenset({
        EventType.TASK_CREATED,
        EventType.TASK_STATE_CHANGED,
        EventType.TASK_COMPLETED,
        EventType.TASK_FAILED,
        EventType.TASK_CANCELLED,
    })

    def __init__(
        self,
        bus: EventBus,
        *,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._bus = bus
        for event_type in self._ALLOWED:
            bus.subscribe(event_type, self._on_event)

    # ------------------------------------------------------------------
    def _on_event(self, event) -> None:
        # Phase 1: log only. Phase 2 will push to JS via the bridge.
        log.debug(
            "event forwarded to GUI layer",
            extra={"event_type": event.type.value, "task_id": event.task_id},
        )