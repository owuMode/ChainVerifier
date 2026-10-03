# tests/integration/test_web_gui_smoke.py
"""
Phase 2d smoke test for the WebEngine GUI.

Phase 3 fixes:
  * ClassifierWorker emits JSON payload.
  * StreamWorker tests explicitly wait for the QThread.
  * WebEngine-heavy tests marked slow.
  * Inline "thinking" box replaces the old tool-cards system.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture(scope="module", autouse=True)
def _offscreen_qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    yield


def _migrations_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "database" / "migrations"


@pytest.fixture
def db(tmp_path: Path):
    from database.manager import DatabaseManager

    database = DatabaseManager(
        db_path=tmp_path / "app.sqlite",
        migrations_dir=_migrations_dir(),
    )
    database.open()
    try:
        yield database
    finally:
        database.close()


# ----------------------------------------------------------------------
# Resources
# ----------------------------------------------------------------------
def test_resources_load():
    from gui.resources.loader import load_chat_html

    html = load_chat_html()

    assert "--accent: #8b5cf6" in html
    assert "QWebChannel = function" in html
    assert "_setupBridge" in html
    assert "whenBridgeReady" in html
    assert "historybridge" in html
    assert "modeMenu" in html

    # Phase 3: inline "thinking" box replaced the old tool-cards.
    assert "ai-thought" in html
    assert "onTaskEvent" in html
    assert "onResponseChunk" in html
    assert "onResponseDone" in html

    # Chat context menu (rename / delete).
    assert "chat-context-menu" in html
    assert "ctxRename" in html
    assert "ctxDelete" in html


def test_missing_resource_raises(tmp_path, monkeypatch):
    from gui.resources import loader

    monkeypatch.setattr(loader, "_HTML_FILE", tmp_path / "nope.html")
    with pytest.raises(FileNotFoundError):
        loader.load_chat_html()


# ----------------------------------------------------------------------
# Fakes
# ----------------------------------------------------------------------
class _FakeChatService:
    def __init__(self, text="hello from fake", error=None, chunks=None):
        self._text = text
        self._error = error
        self._chunks = chunks
        self.calls: list[str] = []

    def reply(self, user_message, history=(), **kwargs):
        from core.services.chat_service import ChatReply
        self.calls.append(user_message)
        return ChatReply(text=self._text, error=self._error)

    def stream_reply(self, user_message, history=(), **kwargs):
        from core.services.chat_service import ChatStreamChunk
        self.calls.append(user_message)

        if self._error:
            yield ChatStreamChunk(
                delta_text=self._text, done=True, error=self._error
            )
            return

        if self._chunks is not None:
            for c in self._chunks:
                yield ChatStreamChunk(delta_text=c, done=False)
            yield ChatStreamChunk(delta_text="", done=True)
            return

        if self._text:
            yield ChatStreamChunk(delta_text=self._text, done=False)
        yield ChatStreamChunk(delta_text="", done=True)

    def handle_memory_command(self, *, action, target, new_value=""):
        from core.services.chat_service import ChatReply
        return ChatReply(text="(memory stub)")


# ----------------------------------------------------------------------
# GuiBridge
# ----------------------------------------------------------------------
def test_gui_bridge_constructs(qt_app):
    from gui.web.bridge import GuiBridge

    bridge = GuiBridge(
        chat_service=None,
        agent=None,
        classifier=None,
        tasks=None,
        config=None,
        modes=None,
    )
    assert bridge is not None
    bridge.requestInitialState()
    bridge.setModel("Rhea Pro")
    bridge.setMode("agent")
    bridge.setMode("invalid-ignored")
    bridge.savePreference("theme", "dark")
    bridge.attachRequested()
    bridge.stopGeneration()


# ----------------------------------------------------------------------
# AgentWorker + ClassifierWorker
# ----------------------------------------------------------------------
def test_agent_worker_constructs(qt_app):
    from gui.web.agent_worker import AgentWorker

    worker = AgentWorker(agent=None, tasks=None, goal="x")
    assert worker.isRunning() is False
    worker.request_cancel()


def test_classifier_worker_constructs(qt_app):
    from gui.web.classifier_worker import ClassifierWorker

    worker = ClassifierWorker(classifier=None, message="hi")
    assert worker.isRunning() is False


def test_stream_worker_constructs(qt_app):
    from gui.web.stream_worker import StreamWorker

    worker = StreamWorker(
        chat_service=None,
        user_message="hi",
        model="test-model",
    )
    assert worker.isRunning() is False
    worker.request_cancel()


# ----------------------------------------------------------------------
# HistoryBridge
# ----------------------------------------------------------------------
def test_history_bridge_roundtrip(qt_app, db):
    from database.repositories import (
        ConversationsRepository,
        MessagesRepository,
    )
    from gui.web.history_bridge import HistoryBridge

    bridge = HistoryBridge(
        conversations_repo=ConversationsRepository(db),
        messages_repo=MessagesRepository(db),
    )

    cid = bridge.ensureConversation("client-1", "")
    assert cid == "client-1"
    bridge.appendMessage("client-1", "assistant", "hello")
    rows = json.loads(bridge.listMessagesJson("client-1"))
    assert rows[0]["role"] == "assistant"


# ----------------------------------------------------------------------
# TaskTracker
# ----------------------------------------------------------------------
def test_task_tracker_forwards_events(qt_app):
    from core.events.bus import EventBus
    from core.events.events import EventType
    from gui.web.task_tracker import TaskTracker

    bus = EventBus()
    tracker = TaskTracker(bus)

    seen: list[str] = []
    tracker.taskEvent.connect(seen.append)

    bus.publish(
        EventType.TASK_CREATED,
        task_id="t-1",
        actor="system",
        payload={"goal": "hello"},
    )

    assert len(seen) == 1
    parsed = json.loads(seen[0])
    assert parsed["type"] == "TASK_CREATED"
    assert parsed["task_id"] == "t-1"
    assert parsed["payload"]["goal"] == "hello"


# ----------------------------------------------------------------------
# WebEngine-heavy tests (slow)
# ----------------------------------------------------------------------
@pytest.mark.slow
def test_bridge_send_message_chat_mode(qt_app):
    from PySide6.QtCore import QEventLoop, QTimer

    from gui.web.bridge import GuiBridge

    svc = _FakeChatService(text="chat reply")
    bridge = GuiBridge(
        chat_service=svc,
        agent=None,
        classifier=None,
        tasks=None,
        config=None,
        modes=None,
    )
    bridge.setMode("chat")

    received: list[str] = []
    bridge.responseReady.connect(received.append)

    loop = QEventLoop()
    bridge.responseReady.connect(loop.quit)
    bridge.responseError.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)

    bridge.sendMessage("hello", "Rhea")
    loop.exec()

    if bridge._chat_worker is not None:
        bridge._chat_worker.wait(2000)

    assert svc.calls == ["hello"]
    assert received == ["chat reply"]


@pytest.mark.slow
def test_bridge_send_message_streams_chunks(qt_app):
    from PySide6.QtCore import QEventLoop, QTimer

    from gui.web.bridge import GuiBridge

    svc = _FakeChatService(chunks=["Hel", "lo ", "world"])
    bridge = GuiBridge(
        chat_service=svc,
        agent=None,
        classifier=None,
        tasks=None,
        config=None,
        modes=None,
    )
    bridge.setMode("chat")

    chunks: list[str] = []
    done: list[str] = []
    ready: list[str] = []

    bridge.streamChunk.connect(chunks.append)
    bridge.streamDone.connect(done.append)
    bridge.responseReady.connect(ready.append)

    loop = QEventLoop()
    bridge.streamDone.connect(loop.quit)
    bridge.responseError.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)

    bridge.sendMessage("hi", "Rhea")
    loop.exec()

    if bridge._stream_worker is not None:
        bridge._stream_worker.wait(2000)

    assert chunks == ["Hel", "lo ", "world"]
    assert done == ["Hello world"]
    assert ready == ["Hello world"]


@pytest.mark.slow
def test_agent_worker_no_agent_errors(qt_app):
    from PySide6.QtCore import QEventLoop, QTimer

    from gui.web.agent_worker import AgentWorker

    worker = AgentWorker(agent=None, tasks=None, goal="x")
    errors: list[str] = []
    worker.finishedErr.connect(errors.append)

    loop = QEventLoop()
    worker.finishedErr.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)

    worker.start()
    loop.exec()
    worker.wait(2000)

    assert errors
    assert "not configured" in errors[0].lower() or "api key" in errors[0].lower()


@pytest.mark.slow
def test_classifier_worker_fallback_without_classifier(qt_app):
    from PySide6.QtCore import QEventLoop, QTimer

    from gui.web.classifier_worker import ClassifierWorker

    worker = ClassifierWorker(classifier=None, message="hi")
    payloads: list[str] = []
    worker.finishedOk.connect(payloads.append)

    loop = QEventLoop()
    worker.finishedOk.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)

    worker.start()
    loop.exec()
    worker.wait(2000)

    assert len(payloads) == 1
    payload = json.loads(payloads[0])
    assert payload["kind"] == "chat"
    assert payload["confidence"] == 0.0


@pytest.mark.slow
def test_stream_worker_emits_chunks(qt_app):
    from PySide6.QtCore import QEventLoop, QTimer

    from gui.web.stream_worker import StreamWorker

    class _FakeStreamService:
        def stream_reply(self, message, history=(), **kwargs):
            from core.services.chat_service import ChatStreamChunk
            yield ChatStreamChunk(delta_text="Hello", done=False)
            yield ChatStreamChunk(delta_text=" world", done=False)
            yield ChatStreamChunk(delta_text="!", done=False)
            yield ChatStreamChunk(delta_text="", done=True)

    worker = StreamWorker(
        chat_service=_FakeStreamService(),
        user_message="hi",
        model="fake",
    )

    chunks: list[str] = []
    done_text: list[str] = []
    worker.chunkReady.connect(chunks.append)
    worker.done.connect(done_text.append)

    loop = QEventLoop()
    worker.done.connect(loop.quit)
    worker.finishedErr.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)

    worker.start()
    loop.exec()
    worker.wait(3000)

    assert chunks == ["Hello", " world", "!"]
    assert done_text == ["Hello world!"]


@pytest.mark.slow
def test_stream_worker_no_service_errors(qt_app):
    from PySide6.QtCore import QEventLoop, QTimer

    from gui.web.stream_worker import StreamWorker

    worker = StreamWorker(
        chat_service=None,
        user_message="hi",
        model="x",
    )
    errors: list[str] = []
    worker.finishedErr.connect(errors.append)

    loop = QEventLoop()
    worker.finishedErr.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)

    worker.start()
    loop.exec()
    worker.wait(3000)

    assert errors
    assert "not configured" in errors[0].lower() or "api key" in errors[0].lower()


@pytest.mark.slow
def test_stream_worker_error_path(qt_app):
    from PySide6.QtCore import QEventLoop, QTimer

    from core.services.chat_service import ChatStreamChunk
    from gui.web.stream_worker import StreamWorker

    class _FailingStreamService:
        def stream_reply(self, message, history=(), **kwargs):
            yield ChatStreamChunk(delta_text="partial", done=False)
            yield ChatStreamChunk(
                delta_text="boom", done=True, error="boom"
            )

    worker = StreamWorker(
        chat_service=_FailingStreamService(),
        user_message="hi",
        model="fake",
    )

    chunks: list[str] = []
    errors: list[str] = []
    worker.chunkReady.connect(chunks.append)
    worker.finishedErr.connect(errors.append)

    loop = QEventLoop()
    worker.finishedErr.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)

    worker.start()
    loop.exec()
    worker.wait(3000)

    assert chunks == ["partial", "boom"]
    assert errors == ["boom"]


@pytest.mark.slow
def test_chat_window_constructs(qt_app):
    from gui.web.window import ChatWindow

    window = ChatWindow()
    try:
        assert window.windowTitle() == "Rhea AI"
    finally:
        window.deleteLater()


@pytest.mark.slow
def test_chat_window_accepts_all_bridges(qt_app, db):
    from core.events.bus import EventBus
    from database.repositories import (
        ConversationsRepository,
        MessagesRepository,
    )
    from gui.web.bridge import GuiBridge
    from gui.web.history_bridge import HistoryBridge
    from gui.web.task_tracker import TaskTracker
    from gui.web.window import ChatWindow

    window = ChatWindow()
    bridge = GuiBridge(
        chat_service=None,
        agent=None,
        classifier=None,
        tasks=None,
        config=None,
        modes=None,
    )
    hist = HistoryBridge(
        conversations_repo=ConversationsRepository(db),
        messages_repo=MessagesRepository(db),
    )
    tracker = TaskTracker(EventBus())
    try:
        window.attach_bridges(
            bridge=bridge,
            history_bridge=hist,
            task_tracker=tracker,
        )
        assert window._channel is not None
    finally:
        window.deleteLater()