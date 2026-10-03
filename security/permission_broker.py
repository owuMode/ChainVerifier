# security/permission_broker.py
"""
PermissionBroker — mediator between the agent's Executor and the GUI.

Timeout is intentionally moderate (default 60s). If a request sits
unanswered for that long, it auto-denies and the task fails cleanly.
"""

from __future__ import annotations

import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from applog.logger import get_logger
from core.events.bus import EventBus
from core.events.events import EventType

log = get_logger("security.permission_broker")


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ALWAYS = "always"
    ALLOW_CHAT = "allow_chat"


@dataclass(frozen=True)
class PermissionRequest:
    request_id: str
    task_id: str
    tool_id: str
    tool_display_name: str
    reason: str
    permission_level: str
    arguments: dict[str, Any]


@dataclass
class _Pending:
    event: threading.Event
    decision: Optional[PermissionDecision] = None


@dataclass
class _QueuedRequest:
    request_id: str
    task_id: str
    tool_id: str
    tool_display_name: str
    reason: str
    permission_level: str
    arguments: dict[str, Any]
    conversation_id: Optional[str] = None
    event: threading.Event = field(default_factory=threading.Event)
    decision: Optional[PermissionDecision] = None


class PermissionBroker:
    def __init__(
        self,
        bus: EventBus,
        *,
        timeout_s: float = 60.0,
        config=None,
    ) -> None:
        self._bus = bus
        self._timeout_s = float(timeout_s)
        self._config = config
        self._lock = threading.RLock()
        self._pending: dict[str, _Pending] = {}
        self._queue: deque[_QueuedRequest] = deque()
        self._active: Optional[_QueuedRequest] = None
        self._always_allow: set[tuple[str, str]] = set()
        self._global_cancel = threading.Event()

    # ------------------------------------------------------------------
    def request(
        self,
        *,
        task_id: str,
        tool_id: str,
        tool_display_name: str,
        reason: str,
        permission_level: str,
        arguments: Optional[dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
    ) -> PermissionDecision:
        if self._global_cancel.is_set():
            return PermissionDecision.DENY

        with self._lock:
            if (task_id, tool_id) in self._always_allow:
                log.info(
                    "permission auto-allowed (task-level)",
                    extra={"task_id": task_id, "tool_id": tool_id},
                )
                return PermissionDecision.ALLOW

        if conversation_id and self._is_chat_auto_allowed(conversation_id):
            log.info(
                "permission auto-allowed (chat-level)",
                extra={
                    "task_id": task_id,
                    "tool_id": tool_id,
                    "conversation_id": conversation_id,
                },
            )
            return PermissionDecision.ALLOW

        request_id = str(uuid.uuid4())
        entry = _Pending(event=threading.Event())
        safe_args = dict(arguments or {})

        with self._lock:
            self._pending[request_id] = entry

        queued = _QueuedRequest(
            request_id=request_id,
            task_id=task_id,
            tool_id=tool_id,
            tool_display_name=tool_display_name,
            reason=reason,
            permission_level=permission_level,
            arguments=safe_args,
            conversation_id=conversation_id,
        )

        with self._lock:
            self._queue.append(queued)
        self._maybe_dispatch_next()

        decided = False
        while True:
            if self._global_cancel.is_set():
                break
            with self._lock:
                is_active = self._active is queued
            if is_active:
                step = 0.5
                waited = 0.0
                while waited < self._timeout_s:
                    if queued.event.wait(timeout=step):
                        decided = True
                        break
                    if self._global_cancel.is_set():
                        break
                    waited += step
                break
            queued.event.wait(timeout=0.25)
            with self._lock:
                if queued.decision is not None:
                    decided = True
                    break

        with self._lock:
            self._pending.pop(request_id, None)
            try:
                self._queue.remove(queued)
            except ValueError:
                pass
            if self._active is queued:
                self._active = None
        self._maybe_dispatch_next()

        if self._global_cancel.is_set():
            return PermissionDecision.DENY

        if not decided or queued.decision is None:
            log.warning(
                "permission timeout — auto-deny",
                extra={"request_id": request_id, "tool_id": tool_id},
            )
            # Notify the GUI so the card can be dismissed.
            try:
                self._bus.publish(
                    EventType.PERMISSION_DENIED,
                    task_id=task_id,
                    actor="system",
                    payload={
                        "request_id": request_id,
                        "tool_id": tool_id,
                        "reason": "timeout",
                    },
                )
            except Exception:
                pass
            return PermissionDecision.DENY

        if queued.decision is PermissionDecision.ALWAYS:
            with self._lock:
                self._always_allow.add((task_id, tool_id))
            return PermissionDecision.ALLOW

        if queued.decision is PermissionDecision.ALLOW_CHAT:
            if conversation_id:
                self._set_chat_auto_allow(conversation_id, True)
            return PermissionDecision.ALLOW

        return queued.decision

    # ------------------------------------------------------------------
    def resolve(self, request_id: str, decision: str) -> bool:
        try:
            d = PermissionDecision(str(decision).strip().lower())
        except ValueError:
            return False

        with self._lock:
            if self._active is not None and self._active.request_id == request_id:
                self._active.decision = d
                self._active.event.set()
                return True
            for q in self._queue:
                if q.request_id == request_id:
                    q.decision = d
                    q.event.set()
                    return True
            entry = self._pending.get(request_id)
            if entry is None:
                return False
            entry.decision = d
            entry.event.set()
            return True

    # ------------------------------------------------------------------
    def _maybe_dispatch_next(self) -> None:
        with self._lock:
            if self._active is not None:
                return
            while self._queue and self._queue[0].decision is not None:
                self._queue.popleft()
            if not self._queue:
                return
            queued = self._queue.popleft()
            self._active = queued

        try:
            self._bus.publish(
                EventType.PERMISSION_REQUIRED,
                task_id=queued.task_id,
                actor="agent",
                payload={
                    "request_id": queued.request_id,
                    "tool_id": queued.tool_id,
                    "tool_display_name": queued.tool_display_name,
                    "reason": queued.reason,
                    "permission_level": queued.permission_level,
                    "timeout_s": int(self._timeout_s),
                    "arguments": dict(queued.arguments),
                    "preview": _build_preview(queued.tool_id, queued.arguments),
                },
            )
        except Exception:
            log.exception("PERMISSION_REQUIRED publish failed")
            with self._lock:
                queued.decision = PermissionDecision.DENY
                queued.event.set()
                self._active = None
            self._maybe_dispatch_next()
            return

        log.info(
            "permission requested",
            extra={
                "request_id": queued.request_id,
                "task_id": queued.task_id,
                "tool_id": queued.tool_id,
                "timeout_s": self._timeout_s,
            },
        )

    # ------------------------------------------------------------------
    def _is_chat_auto_allowed(self, conversation_id: str) -> bool:
        if self._config is None:
            return False
        try:
            return bool(
                self._config.get(
                    f"permissions.auto_allow.{conversation_id}", False
                )
            )
        except Exception:
            return False

    def _set_chat_auto_allow(self, conversation_id: str, value: bool) -> None:
        if self._config is None:
            return
        try:
            self._config.set(
                f"permissions.auto_allow.{conversation_id}", bool(value)
            )
        except Exception:
            log.exception(
                "could not set chat auto-allow",
                extra={"conversation_id": conversation_id},
            )

    def clear_chat(self, conversation_id: str) -> None:
        if self._config is None or not conversation_id:
            return
        try:
            self._config.set(
                f"permissions.auto_allow.{conversation_id}", False
            )
        except Exception:
            log.exception(
                "could not clear chat auto-allow",
                extra={"conversation_id": conversation_id},
            )

    def is_chat_auto_allowed(self, conversation_id: str) -> bool:
        return self._is_chat_auto_allowed(conversation_id)

    # ------------------------------------------------------------------
    def clear_task(self, task_id: str) -> None:
        with self._lock:
            self._always_allow = {
                pair for pair in self._always_allow if pair[0] != task_id
            }
            for q in list(self._queue):
                if q.task_id == task_id:
                    q.decision = PermissionDecision.DENY
                    q.event.set()
            if self._active is not None and self._active.task_id == task_id:
                self._active.decision = PermissionDecision.DENY
                self._active.event.set()
        self._maybe_dispatch_next()

    def cancel_all(self) -> None:
        log.info("permission broker: cancel_all")
        self._global_cancel.set()
        with self._lock:
            for q in list(self._queue):
                q.decision = PermissionDecision.DENY
                q.event.set()
            self._queue.clear()
            if self._active is not None:
                self._active.decision = PermissionDecision.DENY
                self._active.event.set()
                self._active = None

    def reset(self) -> None:
        log.info("permission broker: reset")
        self._global_cancel.clear()

    def forget_all(self) -> None:
        with self._lock:
            self._always_allow.clear()


# ----------------------------------------------------------------------
def _build_preview(tool_id: str, args: dict[str, Any]) -> str:
    try:
        if tool_id == "filesystem_write":
            return _preview_filesystem_write(args)
        if tool_id == "filesystem_read_many":
            return _preview_filesystem_read_many(args)
    except Exception:
        pass
    return ""


def _preview_filesystem_write(args: dict[str, Any]) -> str:
    action = str(args.get("action", "")).strip().lower()
    path = str(args.get("path", "")).strip()
    dest = str(args.get("destination", "")).strip()
    if action == "write":
        return f"Create or overwrite file: {path}"
    if action == "append":
        return f"Append text to file: {path}"
    if action == "delete":
        return f"Delete file permanently: {path}"
    if action == "move":
        return f"Move: {path}  →  {dest}"
    if action == "mkdir":
        return f"Create folder: {path}"
    if action == "rmdir":
        return f"Remove empty folder: {path}"
    return f"{action or 'operation'}: {path}"


def _preview_filesystem_read_many(args: dict[str, Any]) -> str:
    path = str(args.get("path", "")).strip()
    exts = args.get("extensions") or []
    recursive = bool(args.get("recursive", False))
    parts = [f"Read all files in: {path}"]
    if exts:
        parts.append(f"extensions: {', '.join(str(e) for e in exts)}")
    if recursive:
        parts.append("(recursive)")
    return "  ".join(parts)