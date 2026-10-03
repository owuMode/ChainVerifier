# database/connection.py
"""
SQLite connection factory.

Threading note:
  Agent work runs on a QThread (see gui/threads/worker.py), while the
  rest of the app runs on the UI thread. A single SQLite connection
  cannot be used from multiple threads by default — Python's sqlite3
  enforces this with a check on the creating thread.

  We disable that check (check_same_thread=False) and serialise all
  access through the DatabaseManager's lock. WAL mode + serialised
  access from Python is safe in practice and is the standard pattern.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from applog.logger import get_logger

log = get_logger("database.connection")


def open_connection(
    db_path: Path,
    *,
    busy_timeout_ms: int = 5000,
    journal_mode: str = "WAL",
) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        database=str(db_path),
        timeout=busy_timeout_ms / 1000.0,
        isolation_level=None,            # autocommit; explicit transactions
        detect_types=sqlite3.PARSE_DECLTYPES,
        check_same_thread=False,         # shared across UI + worker threads
    )
    conn.row_factory = sqlite3.Row

    # Pragmas — one-time per connection.
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute(f"PRAGMA journal_mode = {journal_mode};")
    conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms};")
    conn.execute("PRAGMA synchronous = NORMAL;")

    log.info("sqlite opened", extra={"path": str(db_path)})
    return conn