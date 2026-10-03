# gui/web/workers.py
"""
Background workers for the GUI.

Phase 3: ChatWorker and StreamWorker now load recent messages from
the conversation so the LLM sees the full chat history, not just the
current user message.
"""

from __future__ import annotations

import threading
from typing import Optional

from PySide6.QtCore import QThread, Signal

from applog.logger import get_logger
from providers.base.models import ChatMessage, Role

log = get_logger("gui.web.workers")


_MAX_HISTORY = 20


def _load_history(
    messages_repo,
    conversation_id: Optional[str],
) -> tuple[ChatMessage, ...]:
    """
    Return the last N messages of a conversation as ChatMessage tuple.
    Only user + assistant roles are included.
    """
    if messages_repo is None or not conversation_id:
        return ()
    try:
        rows = messages_repo.latest(conversation_id, limit=_MAX_HISTORY)
    except Exception:
        log.exception("could not load history")
        return ()

    out: list[ChatMessage] = []
    for m in rows:
        try:
            role_str = str(getattr(m, "role", "")).strip().lower()
            content = str(getattr(m, "content", "") or "").strip()
        except Exception:
            continue
        if not content:
            continue
        if role_str == "user":
            out.append(ChatMessage(role=Role.USER, content=content))
        elif role_str == "assistant":
            out.append(ChatMessage(role=Role.ASSISTANT, content=content))
    return tuple(out)


class ChatWorker(QThread):
    """Runs ChatService.reply() off the UI thread."""

    finishedOk = Signal(str)
    finishedErr = Signal(str)

    def __init__(
        self,
        *,
        chat_service,
        user_message: str,
        model: str,
        conversation_id: Optional[str] = None,
        messages_repo=None,
        parent: Optional[QThread] = None,
    ) -> None:
        super().__init__(parent)
        self._chat_service = chat_service
        self._user_message = user_message
        self._model = model
        self._conversation_id = conversation_id
        self._messages_repo = messages_repo
        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        history = _load_history(self._messages_repo, self._conversation_id)

        try:
            reply = self._chat_service.reply(
                self._user_message,
                history,
                conversation_id=self._conversation_id,
            )
        except Exception as exc:
            log.exception("ChatWorker: unexpected error")
            self.finishedErr.emit(f"Unexpected error: {type(exc).__name__}")
            return

        if self._cancel_event.is_set():
            log.info("ChatWorker: cancelled before emit")
            return

        if reply.error:
            self.finishedErr.emit(reply.text or reply.error)
            return

        self.finishedOk.emit(reply.text)