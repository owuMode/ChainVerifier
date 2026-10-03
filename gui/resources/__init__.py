# gui/resources/__init__.py
"""
Static UI resources: HTML, CSS, JS, and the QWebChannel bootstrap.

Nothing here imports Qt. This package is pure data.
"""

from gui.resources.loader import load_chat_html

__all__ = ["load_chat_html"]