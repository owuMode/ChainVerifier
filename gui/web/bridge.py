# gui/web/bridge.py
"""
GuiBridge — Python <-> JS boundary for chat / agent / model / mode.

Phase 3:
  * 3-way routing: chat, task, memory_command.
  * memory_command is handled directly by ChatService (no LLM call).
  * stopGeneration cancels the permission broker and all workers.
  * "empty plan" errors fall back to a chat reply.
"""

from __future__ import annotations

import json
import time
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from applog.logger import get_logger
from gui.web.agent_worker import AgentWorker
from gui.web.classifier_worker import ClassifierWorker
from gui.web.stream_worker import StreamWorker
from gui.web.workers import ChatWorker

log = get_logger("gui.web.bridge")


class GuiBridge(QObject):

    responseReady = Signal(str)
    responseError = Signal(str)
    streamChunk = Signal(str)
    streamDone = Signal(str)
    modelChanged = Signal(str)
    modeChanged = Signal(str)
    memoryRemembered = Signal(int)

    def __init__(
        self,
        *,
        chat_service,
        agent,
        classifier,
        tasks,
        config,
        modes,
        memory_extractor_factory=None,
        messages_repo=None,
        memory_manager=None,
        permission_broker=None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._chat_service = chat_service
        self._agent = agent
        self._classifier = classifier
        self._tasks = tasks
        self._config = config
        self._modes = modes

        self._memory_extractor_factory = memory_extractor_factory
        self._messages_repo = messages_repo
        self._memory_manager = memory_manager
        self._permission_broker = permission_broker
        self._extract_workers: list = []

        self._chat_worker: Optional[ChatWorker] = None
        self._stream_worker: Optional[StreamWorker] = None
        self._agent_worker: Optional[AgentWorker] = None
        self._classifier_worker: Optional[ClassifierWorker] = None

        self._current_mode: str = (
            modes.get().value if modes is not None else "auto"
        )
        self._current_model: str = ""
        self._cancel_requested = False
        self._streaming_enabled: bool = bool(
            config.get("providers.stream", True)
        ) if config is not None else True

        self._last_conversation_id: Optional[str] = None
        # Remember what text we're currently processing (for
        # empty-plan fallback to chat).
        self._pending_text: Optional[str] = None
        self._pending_model: str = ""

    # ------------------------------------------------------------------
    @Slot(str, str)
    def sendMessage(self, text: str, model: str) -> None:
        effective_model = self._current_model or model or ""

        log.info(
            "bridge: sendMessage",
            extra={
                "model": effective_model,
                "mode": self._current_mode,
                "len": len(text),
                "streaming": self._streaming_enabled,
                "conversation_id": self._last_conversation_id,
            },
        )

        if self._chat_service is None and self._agent is None:
            self.responseError.emit(
                "No AI provider configured. Open Settings and add an API key."
            )
            return

        if self._busy():
            log.warning("bridge: sendMessage ignored — a run is already active")
            return

        self._cancel_requested = False
        self._pending_text = text
        self._pending_model = effective_model

        if self._permission_broker is not None:
            try:
                self._permission_broker.reset()
            except Exception:
                log.exception("broker.reset failed")

        mode = self._current_mode
        if mode == "chat":
            self._start_chat(text, effective_model)
        elif mode == "agent":
            self._start_agent(text)
        elif mode == "auto":
            self._start_auto(text, effective_model)
        else:
            log.warning("bridge: unknown mode, defaulting to chat", extra={"mode": mode})
            self._start_chat(text, effective_model)

    @Slot(str)
    def setConversation(self, conversation_id: str) -> None:
        cid = str(conversation_id or "").strip() or None
        log.info("bridge: setConversation", extra={"conversation_id": cid})
        self._last_conversation_id = cid

    @Slot()
    def stopGeneration(self) -> None:
        log.info("bridge: stopGeneration")
        self._cancel_requested = True

        if self._permission_broker is not None:
            try:
                self._permission_broker.cancel_all()
            except Exception:
                log.exception("broker.cancel_all failed")

        workers = [
            self._chat_worker,
            self._stream_worker,
            self._agent_worker,
            self._classifier_worker,
        ]

        for worker in workers:
            if worker is not None and worker.isRunning():
                try:
                    worker.request_cancel()
                except Exception:
                    log.exception("request_cancel failed")

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            still = any(w is not None and w.isRunning() for w in workers)
            if not still:
                break
            time.sleep(0.05)

    @Slot(str)
    def setModel(self, name: str) -> None:
        self._current_model = str(name).strip()
        log.info("bridge: model set", extra={"model": self._current_model})
        self.modelChanged.emit(self._current_model)

    @Slot(str)
    def setMode(self, mode: str) -> None:
        mode = str(mode).strip().lower()
        if mode not in ("chat", "agent", "auto"):
            log.warning("bridge: invalid mode", extra={"mode": mode})
            return
        self._current_mode = mode
        if self._modes is not None:
            try:
                from core.services.mode import Mode
                self._modes.set(Mode.from_str(mode))
            except Exception:
                log.exception("could not persist mode")
        self.modeChanged.emit(mode)
        log.info("bridge: mode set", extra={"mode": mode})

    @Slot(str, str)
    def savePreference(self, key: str, value: str) -> None:
        log.info("bridge: savePreference", extra={"key": key, "value": value})

    @Slot()
    def requestInitialState(self) -> None:
        log.info("bridge: requestInitialState")
        self.modeChanged.emit(self._current_mode)

    @Slot()
    def attachRequested(self) -> None:
        log.info("bridge: attachRequested")

    @Slot(str)
    def debugLog(self, message: str) -> None:
        log.info("JS debug", extra={"js_msg": str(message)[:400]})

    # ------------------------------------------------------------------
    def _busy(self) -> bool:
        for worker in (
            self._chat_worker,
            self._stream_worker,
            self._agent_worker,
            self._classifier_worker,
        ):
            if worker is not None and worker.isRunning():
                return True
        return False

    def _start_chat(self, text: str, model: str) -> None:
        if self._chat_service is None:
            self.responseError.emit(
                "Chat service is not configured. Add an API key in Settings."
            )
            return
        if self._streaming_enabled:
            self._start_chat_stream(text, model)
        else:
            self._start_chat_blocking(text, model)

    def _start_chat_blocking(self, text: str, model: str) -> None:
        self._chat_worker = ChatWorker(
            chat_service=self._chat_service,
            user_message=text,
            model=model,
            conversation_id=self._last_conversation_id,
            messages_repo=self._messages_repo,
        )
        self._chat_worker.finishedOk.connect(self._on_chat_ok)
        self._chat_worker.finishedErr.connect(self._on_chat_err)
        self._chat_worker.start()

    def _start_chat_stream(self, text: str, model: str) -> None:
        self._stream_worker = StreamWorker(
            chat_service=self._chat_service,
            user_message=text,
            model=model,
            conversation_id=self._last_conversation_id,
            messages_repo=self._messages_repo,
        )
        self._stream_worker.chunkReady.connect(self._on_stream_chunk)
        self._stream_worker.done.connect(self._on_stream_done)
        self._stream_worker.finishedErr.connect(self._on_stream_err)
        self._stream_worker.start()

    def _start_agent(self, text: str) -> None:
        if self._agent is None or self._tasks is None:
            self.responseError.emit(
                "Agent is not configured. Add an API key in Settings."
            )
            return
        self._agent_worker = AgentWorker(
            agent=self._agent,
            tasks=self._tasks,
            goal=text,
            conversation_id=self._last_conversation_id,
        )
        self._agent_worker.finishedOk.connect(self._on_agent_ok)
        self._agent_worker.finishedErr.connect(self._on_agent_err)
        self._agent_worker.taskCreated.connect(self._on_agent_task_created)
        self._agent_worker.start()

    def _start_auto(self, text: str, model: str) -> None:
        if self._classifier is None:
            log.warning("bridge: no classifier, falling back to chat")
            self._start_chat(text, model)
            return
        self._classifier_worker = ClassifierWorker(
            classifier=self._classifier,
            message=text,
        )
        self._classifier_worker.finishedOk.connect(
            lambda payload, t=text, m=model: self._on_classified_payload(payload, t, m)
        )
        self._classifier_worker.finishedErr.connect(self._on_chat_err)
        self._classifier_worker.start()

    def _on_classified_payload(self, payload_json: str, text: str, model: str) -> None:
        if self._cancel_requested:
            self._cancel_requested = False
            return

        try:
            payload = json.loads(payload_json)
        except Exception:
            log.exception("bridge: bad classifier payload")
            self._start_chat(text, model)
            return

        kind = str(payload.get("kind", "")).strip().lower()

        if kind == "memory_command":
            self._handle_memory_command_from_payload(payload)
            return

        if kind == "task":
            self._start_agent(text)
            return

        self._start_chat(text, model)

    def _handle_memory_command_from_payload(self, payload: dict) -> None:
        if self._chat_service is None:
            self.responseError.emit(
                "Chat service is not configured. Add an API key in Settings."
            )
            return

        log.info(
            "bridge: memory command",
            extra={
                "action": payload.get("memory_action"),
                "target": (payload.get("memory_target") or "")[:60],
            },
        )

        try:
            reply = self._chat_service.handle_memory_command(
                action=str(payload.get("memory_action", "")),
                target=str(payload.get("memory_target", "")),
                new_value=str(payload.get("memory_new_value", "")),
            )
        except Exception:
            log.exception("bridge: memory command handler raised")
            self.responseError.emit(
                "Memory command failed. Please try again."
            )
            return

        text_out = (reply.text or "").strip() or "Okay."
        self.responseReady.emit(text_out)

    def _on_chat_ok(self, text: str) -> None:
        if self._cancel_requested:
            self._cancel_requested = False
            return
        self.responseReady.emit(text)
        self._maybe_extract()

    def _on_chat_err(self, message: str) -> None:
        self.responseError.emit(message)

    def _on_stream_chunk(self, text: str) -> None:
        if self._cancel_requested:
            return
        self.streamChunk.emit(text)

    def _on_stream_done(self, text: str) -> None:
        if self._cancel_requested:
            self._cancel_requested = False
            return
        self.streamDone.emit(text)
        self.responseReady.emit(text)
        self._maybe_extract()

    def _on_stream_err(self, message: str) -> None:
        self.responseError.emit(message)

    def _on_agent_task_created(self, task_id: str) -> None:
        log.info("bridge: agent task created", extra={"task_id": task_id})

    def _on_agent_ok(self, final_message: str) -> None:
        if self._cancel_requested:
            self._cancel_requested = False
            return
        self.responseReady.emit(final_message)
        self._maybe_extract()

    def _on_agent_err(self, message: str) -> None:
        # If the agent returned an empty plan (which usually means the
        # request was not actually a task), fall back to a chat reply
        # instead of showing a hardcoded error.
        low = (message or "").lower()
        if ("empty plan" in low) or ("planner returned" in low):
            if self._pending_text and self._chat_service is not None:
                log.info(
                    "bridge: agent empty plan → chat fallback",
                    extra={"text": self._pending_text[:80]},
                )
                self._start_chat(self._pending_text, self._pending_model)
                return
        self.responseError.emit(message)

    # ------------------------------------------------------------------
    def _maybe_extract(self) -> None:
        if self._memory_extractor_factory is None or self._messages_repo is None:
            log.info("memory extract: skipped (missing factory or repo)")
            return
        if self._memory_manager is None:
            log.info("memory extract: skipped (no memory manager)")
            return
        if not self._last_conversation_id:
            log.info("memory extract: skipped (no active conversation)")
            return

        enabled = True
        if self._config is not None:
            try:
                enabled = bool(self._config.get("memory.enabled", True))
            except Exception:
                enabled = True
        if not enabled:
            log.info("memory extract: skipped (disabled in settings)")
            return

        result = self._memory_extractor_factory()
        if result is None:
            log.info("memory extract: factory returned None")
            return
        try:
            extractor, model = result
        except Exception:
            log.exception("memory extractor factory returned bad value")
            return

        from gui.web.memory_extract_worker import MemoryExtractWorker

        log.info(
            "memory extract: starting worker",
            extra={"conv": self._last_conversation_id, "model": model},
        )

        worker = MemoryExtractWorker(
            extractor=extractor,
            memory_manager=self._memory_manager,
            messages_repo=self._messages_repo,
            conversation_id=self._last_conversation_id,
            model=model,
        )
        self._extract_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._forget_extract_worker(w))
        worker.extracted.connect(self._on_memory_extracted)
        worker.start()

    def _forget_extract_worker(self, worker) -> None:
        try:
            self._extract_workers.remove(worker)
        except ValueError:
            pass

    def _on_memory_extracted(self, count: int) -> None:
        try:
            self.memoryRemembered.emit(int(count))
        except Exception:
            pass