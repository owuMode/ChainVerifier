# core/events/handlers.py
"""
Event handlers — the built-in subscribers wired at bootstrap.

Currently one handler:
  AuditBridge — mirrors every event into the `events` table via
                AuditRepository. This is the "everything leaves a trace"
                rule from spec §52 and §109.32.

Rules:
  * Handlers must be fast and must never raise (the bus swallows
    exceptions, but we still keep them clean).
  * AuditBridge must not import EventBus, or a cycle forms.
  * AuditBridge must not fail if the DB is already closed. During
    shutdown, an event may still be published by other hooks after
    the DB has been closed. We skip cleanly in that case.
"""

from __future__ import annotations

from applog.logger import get_logger
from core.events.bus import Event
from database.manager import DatabaseManager
from database.repositories.audit import AuditRepository

log = get_logger("core.events.handlers")


class AuditBridge:
    """
    Subscribes to every EventType and appends a row to the `events` table.

    Redaction is handled inside AuditRepository — this handler passes
    the payload through untouched.
    """

    def __init__(self, audit: AuditRepository, db: DatabaseManager) -> None:
        self._audit = audit
        self._db = db

    def attach(self, bus) -> None:  # bus: EventBus — avoid import cycle
        from core.events.events import EventType

        for event_type in EventType:
            bus.subscribe(event_type, self._on_event)

    # ------------------------------------------------------------------
    def _on_event(self, event: Event) -> None:
        # During shutdown the DB may already be closed. Skipping is
        # correct: there is nowhere to write, and the event is not
        # critical to durability.
        if not self._db.is_open():
            return

        try:
            self._audit.append(
                event.type.value,
                actor=event.actor,
                session_id=event.session_id,
                task_id=event.task_id,
                payload=event.payload,
            )
        except Exception:
            # Audit must never break the pipeline that produced the event.
            log.exception(
                "audit bridge failed",
                extra={"event_type": event.type.value},
            )