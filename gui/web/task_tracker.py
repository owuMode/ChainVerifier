# gui/web/task_tracker.py
"""
TaskTracker — subscribe to EventBus and forward task-related events
to the GUI as structured signals.
"""

from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import QObject, Signal

from applog.logger import get_logger
from core.events.bus import Event, EventBus
from core.events.events import EventType

log = get_logger("gui.web.task_tracker")


class TaskTracker(QObject):
    taskEvent = Signal(str)

    def __init__(
        self,
        bus: EventBus,
        *,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._bus = bus

        for event_type in (
            EventType.TASK_CREATED,
            EventType.TASK_STATE_CHANGED,
            EventType.TASK_UPDATED,
            EventType.TASK_COMPLETED,
            EventType.TASK_FAILED,
            EventType.TASK_CANCELLED,
            EventType.TOOL_STARTED,
            EventType.TOOL_COMPLETED,
            EventType.TOOL_FAILED,
            EventType.SYNTHESIS_CHUNK,
        ):
            bus.subscribe(event_type, self._on_event)

    # ------------------------------------------------------------------
    def _on_event(self, event: Event) -> None:
        try:
            payload = {
                "type": event.type.value,
                "task_id": event.task_id,
                "payload": _sanitize(event.payload),
            }
            log.info(
                "TaskTracker forwarding",
                extra={
                    "type": event.type.value,
                    "task_id": event.task_id,
                },
            )
            self.taskEvent.emit(json.dumps(payload, ensure_ascii=False))
        except Exception:
            log.exception(
                "TaskTracker: failed to forward event",
                extra={"event_type": event.type.value},
            )


def _sanitize(payload: dict) -> dict:
    out: dict = {}
    for k, v in (payload or {}).items():
        if v is None or isinstance(v, (bool, int, float)):
            out[k] = v
        elif isinstance(v, str):
            # Keep chunks readable (synthesis chunks can be long).
            if k == "chunk":
                out[k] = v if len(v) <= 2000 else v[:2000] + "…"
            else:
                out[k] = v if len(v) <= 500 else v[:500] + "…"
        elif isinstance(v, list):
            out[k] = [_primitive(x) for x in v[:20]]
        elif isinstance(v, dict):
            out[k] = {kk: _primitive(vv) for kk, vv in list(v.items())[:20]}
    return out


def _primitive(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 500 else value[:500] + "…"
    return str(value)[:200]