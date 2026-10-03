# core/events/bus.py
"""
EventBus — synchronous, thread-safe pub/sub (spec §45).

Design decisions:
  * Synchronous. Handlers run in the caller's thread. This keeps
    ordering deterministic and makes debugging possible. Long-running
    work belongs in a worker that the handler spawns — not in the
    handler itself.
  * Thread-safe subscribe/unsubscribe/publish.
  * A misbehaving handler MUST NOT break the publisher or other
    handlers. Exceptions are logged and swallowed.
  * Publishing inside a handler is allowed and preserves ordering.
  * No wildcard subscriptions yet. Add when there's a real need.
  * Handlers are invoked in subscription order.
  * Unsubscribing during dispatch is safe: we snapshot before iterating.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional

from applog.logger import get_logger
from core.events.events import EventType

log = get_logger("core.events.bus")


@dataclass(frozen=True)
class Event:
    """A single published event."""
    type: EventType
    payload: dict[str, Any]
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    actor: str = "system"


Handler = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handlers: dict[EventType, list[Handler]] = {}

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------
    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        with self._lock:
            self._handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: EventType, handler: Handler) -> None:
        with self._lock:
            handlers = self._handlers.get(event_type)
            if not handlers:
                return
            try:
                handlers.remove(handler)
            except ValueError:
                return
            if not handlers:
                self._handlers.pop(event_type, None)

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------
    def publish(
        self,
        event_type: EventType,
        *,
        payload: Optional[dict[str, Any]] = None,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        actor: str = "system",
    ) -> Event:
        event = Event(
            type=event_type,
            payload=payload or {},
            task_id=task_id,
            session_id=session_id,
            actor=actor,
        )
        self.publish_event(event)
        return event

    def publish_event(self, event: Event) -> None:
        # Snapshot under lock, dispatch outside lock so handlers may
        # subscribe / unsubscribe / publish without deadlocking.
        with self._lock:
            handlers = list(self._handlers.get(event.type, []))

        for handler in handlers:
            try:
                handler(event)
            except Exception:
                log.exception(
                    "event handler failed",
                    extra={
                        "event_type": event.type.value,
                        "handler": getattr(handler, "__qualname__", repr(handler)),
                    },
                )

    # ------------------------------------------------------------------
    # Introspection (tests / debugging)
    # ------------------------------------------------------------------
    def handler_count(self, event_type: EventType) -> int:
        with self._lock:
            return len(self._handlers.get(event_type, []))