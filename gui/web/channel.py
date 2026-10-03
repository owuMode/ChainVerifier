# gui/web/channel.py
"""
QWebChannel bootstrap.

Registers one or more bridge objects into a QWebEnginePage so
JavaScript can reach them via `window.<name>`.

Currently registered:
    * pybridge       — GuiBridge    (chat / agent / model)
    * historybridge  — HistoryBridge (conversations / messages)
"""

from __future__ import annotations

from typing import Mapping

from PySide6.QtCore import QObject
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage

from applog.logger import get_logger

log = get_logger("gui.web.channel")


def attach_bridges(
    page: QWebEnginePage,
    bridges: Mapping[str, QObject],
) -> QWebChannel:
    """
    Register every (name -> bridge) pair on a single QWebChannel.

    Returns the channel so the caller can keep a reference alive.
    """
    channel = QWebChannel(page)
    for name, bridge in bridges.items():
        channel.registerObject(name, bridge)

    page.setWebChannel(channel)
    log.info("web channel attached", extra={"objects": sorted(bridges.keys())})
    return channel