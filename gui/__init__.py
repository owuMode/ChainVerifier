# gui/__init__.py
"""
GUI package — PySide6 + QtWebEngine.

The entire user interface is rendered from gui/resources/chat.html,
styled by gui/resources/chat.css, and driven by gui/resources/chat.js.

Python <-> JS bridge lives in gui.web.bridge.
"""

__all__: list[str] = []