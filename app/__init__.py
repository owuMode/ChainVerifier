# app/__init__.py
from app.bootstrap import bootstrap
from app.dependencies import AppContext
from app.lifecycle import install_atexit, register_shutdown_hook, shutdown

__all__ = [
    "bootstrap",
    "AppContext",
    "install_atexit",
    "register_shutdown_hook",
    "shutdown",
]