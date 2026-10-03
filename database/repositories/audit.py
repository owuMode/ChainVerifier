# database/repositories/audit.py
"""
AuditRepository — append-only writer/reader for the `events` table.

Layering (spec §89, §96):
  * This module owns the SQL for `events`.
  * It uses `security.redaction` for the redaction step — that is the
    only coupling between database and security, and it is a leaf
    import (security.redaction has no database dependency).
  * The security package does NOT re-export this class. Callers import
    it directly from here.

Redaction happens BEFORE insert. It is also applied on read for defense
in depth in case a row was written by an older code path.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from database.manager import DatabaseManager
from security.redaction import redact_mapping


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    event_type: str
    created_at: str
    session_id: Optional[str]
    task_id: Optional[str]
    actor: str
    payload: dict


class AuditRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    def append(
        self,
        event_type: str,
        *,
        actor: str = "system",
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> AuditEvent:
        safe_payload = redact_mapping(payload or {})
        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            created_at=datetime.now(timezone.utc).isoformat(),
            session_id=session_id,
            task_id=task_id,
            actor=actor,
            payload=safe_payload,
        )
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO events
                    (event_id, event_type, created_at, session_id, task_id, actor, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.created_at,
                    event.session_id,
                    event.task_id,
                    event.actor,
                    json.dumps(event.payload, ensure_ascii=False),
                ),
            )
        return event

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def recent(self, limit: int = 100) -> list[AuditEvent]:
        rows = self._db.connection.execute(
            "SELECT * FROM events ORDER BY created_at DESC LIMIT ?;",
            (limit,),
        ).fetchall()
        return [_row_to_event(r) for r in rows]

    def by_task(self, task_id: str, limit: int = 500) -> list[AuditEvent]:
        rows = self._db.connection.execute(
            """
            SELECT * FROM events
            WHERE task_id = ?
            ORDER BY created_at ASC
            LIMIT ?;
            """,
            (task_id, limit),
        ).fetchall()
        return [_row_to_event(r) for r in rows]


def _row_to_event(row) -> AuditEvent:
    try:
        raw = json.loads(row["payload"]) if row["payload"] else {}
    except json.JSONDecodeError:
        raw = {}
    # Defense in depth: redact again on read.
    safe = redact_mapping(raw)
    return AuditEvent(
        event_id=row["event_id"],
        event_type=row["event_type"],
        created_at=row["created_at"],
        session_id=row["session_id"],
        task_id=row["task_id"],
        actor=row["actor"],
        payload=safe,
    )