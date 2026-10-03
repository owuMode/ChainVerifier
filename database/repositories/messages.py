# database/repositories/messages.py
"""
MessagesRepository — append/read messages within a conversation.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

from database.manager import DatabaseManager


_ALLOWED_ROLES = frozenset({"system", "user", "assistant", "tool"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Message:
    message_id: str
    conversation_id: str
    role: str
    content: str
    created_at: str
    metadata: dict


class MessagesRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def append(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> Message:
        if role not in _ALLOWED_ROLES:
            raise ValueError(f"invalid role: {role!r}")

        msg = Message(
            message_id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=_utc_now(),
            metadata=metadata or {},
        )
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO messages
                    (message_id, conversation_id, role, content, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    msg.message_id,
                    msg.conversation_id,
                    msg.role,
                    msg.content,
                    msg.created_at,
                    json.dumps(msg.metadata, ensure_ascii=False),
                ),
            )
        return msg

    def list_for_conversation(self, conversation_id: str) -> list[Message]:
        rows = self._db.connection.execute(
            """
            SELECT * FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC;
            """,
            (conversation_id,),
        ).fetchall()
        return [_row_to_message(r) for r in rows]

    def latest(self, conversation_id: str, limit: int = 20) -> Iterable[Message]:
        rows = self._db.connection.execute(
            """
            SELECT * FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?;
            """,
            (conversation_id, limit),
        ).fetchall()
        return [_row_to_message(r) for r in reversed(rows)]


def _row_to_message(row) -> Message:
    try:
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
    except json.JSONDecodeError:
        meta = {}
    return Message(
        message_id=row["message_id"],
        conversation_id=row["conversation_id"],
        role=row["role"],
        content=row["content"],
        created_at=row["created_at"],
        metadata=meta,
    )