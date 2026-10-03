# tests/integration/conftest.py
from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    # Do not quit the app between tests — Qt is picky about that.