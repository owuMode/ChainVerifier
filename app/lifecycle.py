# app/lifecycle.py
"""
Lifecycle — clean shutdown sequence (spec §68).

    Stop accepting new tasks
      → Cancel/finish safe operations
        → Flush events
          → Persist state
            → Close database
              → Release native resources

In Step 1 the only thing to release is logging. Later steps register
their own shutdown hooks via `register_shutdown_hook()`.
"""

from __future__ import annotations

import atexit
import logging
import threading
from typing import Callable

from app.dependencies import AppContext
from applog.logger import get_logger


_hooks: list[tuple[str, Callable[[AppContext], None]]] = []
_lock = threading.Lock()
_shutdown_started = False


def register_shutdown_hook(name: str, hook: Callable[[AppContext], None]) -> None:
    """Register a shutdown callback. Hooks run in reverse registration order."""
    with _lock:
        _hooks.append((name, hook))


def shutdown(ctx: AppContext) -> None:
    global _shutdown_started
    with _lock:
        if _shutdown_started:
            return
        _shutdown_started = True

    log = get_logger("lifecycle")
    log.info("shutdown requested")

    for name, hook in reversed(_hooks):
        try:
            hook(ctx)
            log.info("shutdown hook ok", extra={"hook": name})
        except Exception:
            log.exception("shutdown hook failed", extra={"hook": name})

    # Flush logging last so prior hooks get their logs recorded.
    logging.shutdown()


def install_atexit(ctx: AppContext) -> None:
    atexit.register(shutdown, ctx)