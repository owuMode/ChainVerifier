# gui/web/window.py
"""
ChatWindow — the application's main window.

Features:
  * Right-click disabled on the WebEngine view.
  * Window opens maximized.
  * JS dialogs (alert/confirm/prompt) display a clean title.
  * Graceful shutdown cancels running agent work.
"""

from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import QUrl, Qt, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout

from applog.logger import get_logger
from gui.resources.loader import load_chat_html
from gui.web.bridge import GuiBridge
from gui.web.channel import attach_bridges
from gui.web.history_bridge import HistoryBridge
from gui.web.memory_bridge import MemoryBridge
from gui.web.permission_bridge import PermissionBridge
from gui.web.provider_bridge import ProviderBridge
from gui.web.settings_bridge import SettingsBridge
from gui.web.task_tracker import TaskTracker
from gui.web.tasks_bridge import TasksBridge

log = get_logger("gui.web.window")


class _NoContextMenuWebView(QWebEngineView):
    """
    QWebEngineView subclass that:
      * Ignores context-menu requests entirely.
      * Rewrites the internal page title shown in JS dialog windows.
    """

    def contextMenuEvent(self, event) -> None:
        event.accept()


class ChatWindow(QMainWindow):

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.setWindowTitle("Rhea AI")
        self.resize(1280, 820)
        self.setMinimumSize(850, 560)

        self._bridge: Optional[GuiBridge] = None
        self._history_bridge: Optional[HistoryBridge] = None
        self._provider_bridge: Optional[ProviderBridge] = None
        self._tasks_bridge: Optional[TasksBridge] = None
        self._settings_bridge: Optional[SettingsBridge] = None
        self._permission_bridge: Optional[PermissionBridge] = None
        self._memory_bridge: Optional[MemoryBridge] = None
        self._task_tracker: Optional[TaskTracker] = None
        self._channel = None

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self._view = _NoContextMenuWebView(central)
        layout.addWidget(self._view)
        self.setCentralWidget(central)

        # Set the WebEngine page's title. This is what appears in the
        # window bar of JavaScript alert/confirm/prompt dialogs.
        self._view.page().titleChanged.connect(self._on_page_title)
        # And also set it once the page loads.
        self._view.loadFinished.connect(self._on_load_finished)

        # JS dialogs: default is a QWebEnginePage-managed dialog with
        # a title bar taken from the page's <title>. We override the
        # window title of this main window instead — cleaner UX.
        try:
            self._view.page().setBackgroundColor(Qt.transparent)
        except Exception:
            pass

        try:
            settings = self._view.settings()
            settings.setAttribute(
                QWebEngineSettings.WebAttribute.JavascriptEnabled, True
            )
            settings.setAttribute(
                QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
                True,
            )
            # Allow JS to use the clipboard API without extra prompt.
            settings.setAttribute(
                QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard,
                True,
            )
            settings.setAttribute(
                QWebEngineSettings.WebAttribute.JavascriptCanPaste,
                True,
            )
        except Exception:
            log.exception("could not set WebEngine settings")

        html = load_chat_html()
        self._view.setHtml(html, QUrl("https://rhea.local/"))

        log.info("chat window created")

    # ------------------------------------------------------------------
    @Slot(str)
    def _on_page_title(self, title: str) -> None:
        # We do not allow the page to change the main window's title.
        # (JS dialog titles are handled by Qt internally, but we keep
        # the main window title constant.)
        if title != "Rhea AI":
            try:
                self.setWindowTitle("Rhea AI")
            except Exception:
                pass

    @Slot(bool)
    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            log.warning("page load failed")
            return
        # Force the document title to "Rhea AI" so any future JS
        # dialogs use a clean title.
        script = "document.title = 'Rhea AI';"
        self._view.page().runJavaScript(script)

    # ------------------------------------------------------------------
    def attach_bridges(
        self,
        *,
        bridge: GuiBridge,
        history_bridge: HistoryBridge,
        provider_bridge: Optional[ProviderBridge] = None,
        tasks_bridge: Optional[TasksBridge] = None,
        settings_bridge: Optional[SettingsBridge] = None,
        permission_bridge: Optional[PermissionBridge] = None,
        memory_bridge: Optional[MemoryBridge] = None,
        task_tracker: Optional[TaskTracker] = None,
    ) -> None:
        self._bridge = bridge
        self._history_bridge = history_bridge
        self._provider_bridge = provider_bridge
        self._tasks_bridge = tasks_bridge
        self._settings_bridge = settings_bridge
        self._permission_bridge = permission_bridge
        self._memory_bridge = memory_bridge
        self._task_tracker = task_tracker

        bridges = {
            "pybridge": bridge,
            "historybridge": history_bridge,
        }
        if provider_bridge is not None:
            bridges["providerbridge"] = provider_bridge
        if tasks_bridge is not None:
            bridges["tasksbridge"] = tasks_bridge
        if settings_bridge is not None:
            bridges["settingsbridge"] = settings_bridge
        if permission_bridge is not None:
            bridges["permissionbridge"] = permission_bridge
        if memory_bridge is not None:
            bridges["memorybridge"] = memory_bridge

        self._channel = attach_bridges(self._view.page(), bridges)

        bridge.responseReady.connect(self._on_response_ready)
        bridge.responseError.connect(self._on_response_error)
        bridge.modelChanged.connect(self._on_model_changed)
        bridge.modeChanged.connect(self._on_mode_changed)
        bridge.streamChunk.connect(self._on_stream_chunk)
        bridge.streamDone.connect(self._on_stream_done)
        bridge.memoryRemembered.connect(self._on_memory_remembered)

        history_bridge.conversationsChanged.connect(self._on_conversations_changed)

        if provider_bridge is not None:
            provider_bridge.providerChanged.connect(self._on_provider_changed)
            provider_bridge.apiKeyChanged.connect(self._on_api_key_changed)

        if tasks_bridge is not None:
            tasks_bridge.tasksChanged.connect(self._on_tasks_changed)

        if settings_bridge is not None:
            settings_bridge.storageChanged.connect(self._on_storage_changed)

        if permission_bridge is not None:
            permission_bridge.permissionRequested.connect(self._on_permission_requested)
            permission_bridge.permissionResolved.connect(self._on_permission_resolved)

        if memory_bridge is not None:
            memory_bridge.memoryChanged.connect(self._on_memory_changed)
            memory_bridge.enabledChanged.connect(self._on_memory_enabled_changed)

        if task_tracker is not None:
            task_tracker.taskEvent.connect(self._on_task_event)

        log.info("bridges attached to chat window")

    # ------------------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:
        log.info("chat window closing")
        if self._bridge is not None:
            try:
                self._bridge.stopGeneration()
            except Exception:
                log.exception("stopGeneration during close failed")
        super().closeEvent(event)

    # ------------------------------------------------------------------
    @Slot(str)
    def _on_response_ready(self, text: str) -> None:
        self._run_js("onResponseReady", text)

    @Slot(str)
    def _on_response_error(self, message: str) -> None:
        self._run_js("onResponseError", message)

    @Slot(str)
    def _on_stream_chunk(self, text: str) -> None:
        self._run_js("onResponseChunk", text)

    @Slot(str)
    def _on_stream_done(self, text: str) -> None:
        self._run_js("onResponseDone", text)

    @Slot(str)
    def _on_model_changed(self, name: str) -> None:
        self._run_js("onModelChanged", name)

    @Slot(str)
    def _on_mode_changed(self, mode: str) -> None:
        self._run_js("onModeChanged", mode)

    @Slot()
    def _on_conversations_changed(self) -> None:
        self._run_js_noarg("onConversationsChanged")

    @Slot(str)
    def _on_provider_changed(self, key: str) -> None:
        self._run_js("onProviderChangedFromPython", key)

    @Slot(str)
    def _on_api_key_changed(self, key: str) -> None:
        self._run_js("onApiKeyChangedFromPython", key)

    @Slot()
    def _on_tasks_changed(self) -> None:
        self._run_js_noarg("onTasksChangedFromPython")

    @Slot(str)
    def _on_storage_changed(self, path: str) -> None:
        log.info("storage changed (bridge signal)", extra={"path": path})

    @Slot(str)
    def _on_permission_requested(self, payload_json: str) -> None:
        script = (
            "window.onPermissionRequested && "
            f"window.onPermissionRequested({json.dumps(payload_json)});"
        )
        self._view.page().runJavaScript(script)

    @Slot(str)
    def _on_permission_resolved(self, payload_json: str) -> None:
        script = (
            "window.onPermissionResolved && "
            f"window.onPermissionResolved({json.dumps(payload_json)});"
        )
        self._view.page().runJavaScript(script)

    @Slot()
    def _on_memory_changed(self) -> None:
        self._run_js_noarg("refreshMemorySection")

    @Slot(bool)
    def _on_memory_enabled_changed(self, enabled: bool) -> None:
        script = (
            "window.onMemoryEnabledChanged && "
            f"window.onMemoryEnabledChanged({str(bool(enabled)).lower()});"
        )
        self._view.page().runJavaScript(script)

    @Slot(int)
    def _on_memory_remembered(self, count: int) -> None:
        script = (
            "window.onMemoryRemembered && "
            f"window.onMemoryRemembered({int(count)});"
        )
        self._view.page().runJavaScript(script)

    @Slot(str)
    def _on_task_event(self, payload_json: str) -> None:
        script = f"window.onTaskEvent && window.onTaskEvent({json.dumps(payload_json)});"
        self._view.page().runJavaScript(script)

    # ------------------------------------------------------------------
    def _run_js(self, function_name: str, argument: str) -> None:
        payload = json.dumps(argument)
        script = f"window.{function_name} && window.{function_name}({payload});"
        self._view.page().runJavaScript(script)

    def _run_js_noarg(self, function_name: str) -> None:
        script = f"window.{function_name} && window.{function_name}();"
        self._view.page().runJavaScript(script)