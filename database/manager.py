# database/manager.py
"""
DatabaseManager — the single owner of the SQLite connection.

Threading:
  * One connection shared across UI thread and worker threads.
  * check_same_thread=False (set in connection.py).
  * All access is serialised through `self._lock` (RLock).
  * `transaction()` is the only sanctioned multi-statement block.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from applog.logger import get_logger
from database.connection import open_connection
from database.migrations.runner import run_migrations

log = get_logger("database.manager")


class DatabaseError(Exception):
    pass


class DatabaseManager:
    def __init__(
        self,
        db_path: Path,
        migrations_dir: Path,
        *,
        busy_timeout_ms: int = 5000,
        journal_mode: str = "WAL",
    ) -> None:
        self._db_path = db_path
        self._migrations_dir = migrations_dir
        self._busy_timeout_ms = busy_timeout_ms
        self._journal_mode = journal_mode
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def open(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            self._conn = open_connection(
                self._db_path,
                busy_timeout_ms=self._busy_timeout_ms,
                journal_mode=self._journal_mode,
            )
            version = run_migrations(self._conn, self._migrations_dir)
            log.info("database ready", extra={"schema_version": version})

    def close(self) -> None:
        with self._lock:
            if self._conn is None:
                return
            try:
                self._conn.close()
            finally:
                self._conn = None
            log.info("database closed")

    def is_open(self) -> bool:
        with self._lock:
            return self._conn is not None

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------
    @property
    def connection(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is None:
                raise DatabaseError("database is not open")
            return self._conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self.connection
            if conn.in_transaction:
                yield conn
                return
            conn.execute("BEGIN;")
            try:
                yield conn
            except Exception:
                conn.execute("ROLLBACK;")
                raise
            else:
                conn.execute("COMMIT;")