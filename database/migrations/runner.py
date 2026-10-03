# database/migrations/runner.py
"""
Migration runner.

Rules (spec §36):
  * Migrations live as numbered .sql files in this directory.
  * Runner is idempotent: already-applied versions are skipped.
  * Each migration runs inside an explicit transaction.
  * Never edit a migration that has shipped — add a new one.

Note on `extra=`:
  Python's logging raises KeyError if `extra=` contains a reserved
  LogRecord attribute (name, msg, args, levelname, ...). We therefore
  use "migration" instead of "name" for the migration's human name.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from applog.logger import get_logger

log = get_logger("database.migrations")

_MIGRATION_RE = re.compile(r"^migration_(\d+)_(.+)\.sql$")


# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------
def _discover(migrations_dir: Path) -> list[tuple[int, str, Path]]:
    found: list[tuple[int, str, Path]] = []
    for path in sorted(migrations_dir.glob("migration_*.sql")):
        match = _MIGRATION_RE.match(path.name)
        if not match:
            log.warning(
                "ignoring malformed migration filename",
                extra={"file": path.name},
            )
            continue
        version = int(match.group(1))
        name = match.group(2)
        found.append((version, name, path))
    found.sort(key=lambda item: item[0])
    return found


# ----------------------------------------------------------------------
# Version bookkeeping
# ----------------------------------------------------------------------
def _current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='schema_version';"
    ).fetchone()
    if row is None:
        return 0
    cur = conn.execute("SELECT MAX(version) AS v FROM schema_version;").fetchone()
    return int(cur["v"]) if cur and cur["v"] is not None else 0


# ----------------------------------------------------------------------
# Run
# ----------------------------------------------------------------------
def run_migrations(conn: sqlite3.Connection, migrations_dir: Path) -> int:
    """
    Apply all pending migrations. Returns the final schema version.
    """
    current = _current_version(conn)
    log.info("migration check", extra={"current": current})

    for version, name, path in _discover(migrations_dir):
        if version <= current:
            continue

        sql = path.read_text(encoding="utf-8")

        try:
            # Autocommit connection: we drive the transaction explicitly.
            conn.execute("BEGIN;")
            for statement in _split_sql(sql):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at, name) "
                "VALUES (?, ?, ?);",
                (version, datetime.now(timezone.utc).isoformat(), name),
            )
            conn.execute("COMMIT;")
        except Exception:
            # Only roll back if a transaction is actually open.
            if conn.in_transaction:
                try:
                    conn.execute("ROLLBACK;")
                except sqlite3.OperationalError:
                    pass
            log.exception(
                "migration failed",
                extra={"version": version, "migration": name},
            )
            raise
        else:
            # Logged AFTER commit — safe: if logging itself fails, the
            # migration has already been persisted.
            log.info(
                "migration applied",
                extra={"version": version, "migration": name},
            )

    return _current_version(conn)


# ----------------------------------------------------------------------
# SQL splitting
# ----------------------------------------------------------------------
def _split_sql(sql: str) -> list[str]:
    """
    Split a .sql file into individual statements on semicolons that are
    not inside a string literal and not inside a comment.

    Simple, predictable — matches the plain style our migrations use.
    """
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(sql)
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False

    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                buf.append(ch)
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if in_single:
            buf.append(ch)
            if ch == "'" and nxt == "'":
                buf.append(nxt)
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue

        if in_double:
            buf.append(ch)
            if ch == '"':
                in_double = False
            i += 1
            continue

        if ch == "-" and nxt == "-":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch == "'":
            in_single = True
            buf.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = True
            buf.append(ch)
            i += 1
            continue

        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements