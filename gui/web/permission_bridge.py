# gui/web/permission_bridge.py
"""
PermissionBridge — Python <-> JS boundary for the permission dialog.

Design:
  * The PermissionBroker publishes PERMISSION_REQUIRED on the bus.
  * This bridge subscribes to that event and emits a Qt signal that
    the window forwards to JS as `onPermissionRequested(payload)`.
  * JS shows an inline card. When the user clicks Allow/Deny/Always,
    JS calls `permissionbridge.resolve(request_id, decision)`.
  * The bridge calls broker.resolve(...) which unblocks the Executor.

The bridge never touches the Executor directly. It only talks to the
broker and the event bus.
"""

from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from applog.logger import get_logger
from core.events.bus import Event, EventBus
from core.events.events import EventType

log = get_logger("gui.web.permission_bridge")


class PermissionBridge(QObject):
    """
    Registered with QWebChannel as `permissionbridge`.
    """

    # Python -> JS: emitted with a JSON string describing the request.
    permissionRequested = Signal(str)

    # Python -> JS: emitted when the request has been resolved (so JS
    # can update the card if the dialog is still visible).
    permissionResolved = Signal(str)   # JSON: {"request_id": "..."}

    def __init__(
        self,
        *,
        broker,
        bus: EventBus,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._broker = broker
        self._bus = bus

        bus.subscribe(EventType.PERMISSION_REQUIRED, self._on_required)

    # ------------------------------------------------------------------
    # Slots (called from JS)
    # ------------------------------------------------------------------
    @Slot(str, str, result=bool)
    def resolve(self, request_id: str, decision: str) -> bool:
        """
        Apply the user's decision. decision is "allow" | "deny" | "always".
        """
        if self._broker is None:
            log.warning("resolve: no broker configured")
            return False

        ok = self._broker.resolve(request_id, decision)
        if ok:
            try:
                self.permissionResolved.emit(
                    json.dumps({"request_id": request_id, "decision": decision})
                )
            except Exception:
                log.exception("permissionResolved emit failed")
        return ok

    # ------------------------------------------------------------------
    def _on_required(self, event: Event) -> None:
        """Forward PERMISSION_REQUIRED events to JS."""
        try:
            payload = dict(event.payload or {})
            payload["task_id"] = event.task_id
            self.permissionRequested.emit(
                json.dumps(payload, ensure_ascii=False)
            )
            log.info(
                "permission forwarded to GUI",
                extra={
                    "request_id": payload.get("request_id"),
                    "tool_id": payload.get("tool_id"),
                },
            )
        except Exception:
            log.exception("failed to forward PERMISSION_REQUIRED")