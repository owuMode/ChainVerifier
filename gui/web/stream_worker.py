# gui/web/stream_worker.py
"""
StreamWorker — run a streaming chat reply off the UI thread.

Phase 3: loads recent conversation history so the LLM sees prior
turns.
"""

from __future__ import annotations

import threading
from typing import Optional

from PySide6.QtCore import QThread, Signal

from applog.logger import get_logger
from providers.base.models import ChatMessage, Role

log = get_logger("gui.web.stream_worker")


_MAX_HISTORY = 20


def _load_history(
    messages_repo,
    conversation_id: Optional[str],
) -> tuple[ChatMessage, ...]:
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


class StreamWorker(QThread):
    chunkReady = Signal(str)
    done = Signal(str)
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
        if self._chat_service is None:
            self.finishedErr.emit(
                "Chat service is not configured. Add an API key in Settings."
            )
            return

        history = _load_history(self._messages_repo, self._conversation_id)

        accumulated: list[str] = []
        error_message: Optional[str] = None

        try:
            for chunk in self._chat_service.stream_reply(
                self._user_message,
                history,
                conversation_id=self._conversation_id,
            ):
                if self._cancel_event.is_set():
                    log.info("StreamWorker: cancelled")
                    return

                if chunk.error:
                    error_message = chunk.delta_text or chunk.error
                    if chunk.delta_text:
                        accumulated.append(chunk.delta_text)
                        self.chunkReady.emit(chunk.delta_text)
                    break

                if chunk.delta_text:
                    accumulated.append(chunk.delta_text)
                    self.chunkReady.emit(chunk.delta_text)

                if chunk.done:
                    break

        except Exception as exc:
            log.exception("StreamWorker: unexpected error")
            self.finishedErr.emit(f"Unexpected error: {type(exc).__name__}")
            return

        if self._cancel_event.is_set():
            return

        final_text = "".join(accumulated).strip()

        if error_message:
            self.finishedErr.emit(error_message)
            return

        if not final_text:
            final_text = "(empty response from model)"

        self.done.emit(final_text)