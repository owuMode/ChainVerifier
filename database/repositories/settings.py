# database/repositories/settings.py
"""
SettingsRepository — JSON-encoded key/value persistence.

Used by ConfigurationService to load/apply overrides (spec §42).
Raw SQL stays here; nothing else touches the settings table.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from applog.logger import get_logger
from database.manager import DatabaseManager

log = get_logger("database.settings")


class SettingsRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def get(self, key: str) -> Optional[Any]:
        row = self._db.connection.execute(
            "SELECT value FROM settings WHERE key = ?;",
            (key,),
        ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            log.warning("invalid JSON in settings", extra={"key": key})
            return None

    def set(self, key: str, value: Any) -> None:
        encoded = json.dumps(value, ensure_ascii=False)
        now = datetime.now(timezone.utc).isoformat()
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at;
                """,
                (key, encoded, now),
            )

    def all(self) -> dict[str, Any]:
        rows = self._db.connection.execute(
            "SELECT key, value FROM settings;"
        ).fetchall()
        out: dict[str, Any] = {}
        for row in rows:
            try:
                out[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                log.warning("invalid JSON in settings", extra={"key": row["key"]})
        return out

    def delete(self, key: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM settings WHERE key = ?;", (key,))