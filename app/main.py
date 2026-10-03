# app/main.py
"""
Application entrypoint — PySide6 + QWebEngineView.

Shutdown:
  * aboutToQuit runs shutdown() on a background thread with a 5s cap.
  * If shutdown does not finish in time, we force-quit the process
    with os._exit(0) so a stuck worker cannot freeze the close.

Window:
  * Opens maximized by default.
"""

from __future__ import annotations

import os
import sys
import threading

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from app.bootstrap import bootstrap
from app.lifecycle import install_atexit, shutdown
from applog.logger import get_logger
from gui.controllers.app_controller import AppController
from gui.web.window import ChatWindow


def _run_shutdown_with_timeout(ctx, timeout_s: float = 5.0) -> None:
    """
    Run shutdown() on a daemon thread. If it doesn't finish in
    `timeout_s`, force-exit the process.
    """
    log = get_logger("main")

    def _worker() -> None:
        try:
            shutdown(ctx)
        except Exception:
            log.exception("shutdown raised")

    t = threading.Thread(target=_worker, name="shutdown", daemon=True)
    t.start()
    t.join(timeout=timeout_s)
    if t.is_alive():
        log.warning(
            "shutdown did not finish in %.1fs — forcing exit", timeout_s
        )
        os._exit(0)


def run() -> int:
    ctx = bootstrap()
    install_atexit(ctx)
    log = get_logger("main")

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Rhea AI")
    qt_app.setApplicationDisplayName("Rhea AI")
    qt_app.setOrganizationName("Rhea AI")

    # Graceful shutdown when Qt exits.
    qt_app.aboutToQuit.connect(lambda: _run_shutdown_with_timeout(ctx, 5.0))

    window = ChatWindow()

    AppController(
        window=window,
        ctx=ctx,
        parent=window,
    )

    # Maximize by default.
    window.showMaximized()
    log.info("GUI shown (maximized)")

    exit_code = qt_app.exec()

    # Safety net in case aboutToQuit was not fired.
    _run_shutdown_with_timeout(ctx, 5.0)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run())