# applog/logger.py
"""
Logger setup — the only place that wires Python's logging to our handlers.

Rules (spec §52):
  * Structured logs to file.
  * Human-readable logs to console.
  * Redaction is always on.
  * Never configure root logger blindly.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Optional

from applog.formatters import HumanFormatter, StructuredFormatter


_CONFIGURED = False
_ROOT_LOGGER_NAME = "aiproduct"


def configure_logging(
    log_dir: Path,
    *,
    level: int = logging.INFO,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
    console: bool = True,
) -> logging.Logger:
    global _CONFIGURED
    root = logging.getLogger(_ROOT_LOGGER_NAME)

    if _CONFIGURED:
        return root

    root.setLevel(level)
    root.propagate = False

    log_dir.mkdir(parents=True, exist_ok=True)

    file_path = log_dir / "app.log"
    file_handler = logging.handlers.RotatingFileHandler(
        filename=str(file_path),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(StructuredFormatter())
    root.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(HumanFormatter())
        root.addHandler(console_handler)

    _CONFIGURED = True
    return root


def get_logger(name: Optional[str] = None) -> logging.Logger:
    if not name:
        return logging.getLogger(_ROOT_LOGGER_NAME)
    if name.startswith(_ROOT_LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")