# database/repositories/conversations.py
"""
ConversationsRepository — CRUD for conversations.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from database.manager import DatabaseManager


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Conversation:
    conversation_id: str
    title: str
    created_at: str
    updated_at: str
    archived: bool
    metadata: dict


class ConversationsRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    # ------------------------------------------------------------------
    def create(
        self,
        title: str = "",
        metadata: Optional[dict] = None,
        conversation_id: Optional[str] = None,
    ) -> Conversation:
        now = _utc_now()
        conv = Conversation(
            conversation_id=conversation_id or str(uuid.uuid4()),
            title=title,
            created_at=now,
            updated_at=now,
            archived=False,
            metadata=metadata or {},
        )
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO conversations
                    (conversation_id, title, created_at, updated_at, archived, metadata)
                VALUES (?, ?, ?, ?, 0, ?);
                """,
                (
                    conv.conversation_id,
                    conv.title,
                    conv.created_at,
                    conv.updated_at,
                    json.dumps(conv.metadata, ensure_ascii=False),
                ),
            )
        return conv

    # ------------------------------------------------------------------
    def get(self, conversation_id: str) -> Optional[Conversation]:
        row = self._db.connection.execute(
            "SELECT * FROM conversations WHERE conversation_id = ?;",
            (conversation_id,),
        ).fetchone()
        return _row_to_conversation(row) if row else None

    def exists(self, conversation_id: str) -> bool:
        row = self._db.connection.execute(
            "SELECT 1 FROM conversations WHERE conversation_id = ? LIMIT 1;",
            (conversation_id,),
        ).fetchone()
        return row is not None

    def list_recent(
        self,
        limit: int = 50,
        include_archived: bool = False,
    ) -> list[Conversation]:
        sql = "SELECT * FROM conversations"
        params: list = []
        if not include_archived:
            sql += " WHERE archived = 0"
        sql += " ORDER BY updated_at DESC LIMIT ?;"
        params.append(limit)
        rows = self._db.connection.execute(sql, params).fetchall()
        return [_row_to_conversation(r) for r in rows]

    # ------------------------------------------------------------------
    def rename(self, conversation_id: str, title: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE conversation_id = ?;",
                (title, _utc_now(), conversation_id),
            )

    def touch(self, conversation_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?;",
                (_utc_now(), conversation_id),
            )

    def set_archived(self, conversation_id: str, archived: bool) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE conversations SET archived = ?, updated_at = ? WHERE conversation_id = ?;",
                (1 if archived else 0, _utc_now(), conversation_id),
            )

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------
    def update_metadata(self, conversation_id: str, updates: dict) -> None:
        """
        Merge `updates` into the existing metadata JSON. Best-effort.
        """
        try:
            conv = self.get(conversation_id)
            if conv is None:
                return
            meta = dict(conv.metadata or {})
            meta.update(updates or {})
            with self._db.transaction() as conn:
                conn.execute(
                    "UPDATE conversations SET metadata = ?, updated_at = ? WHERE conversation_id = ?;",
                    (json.dumps(meta, ensure_ascii=False), _utc_now(), conversation_id),
                )
        except Exception:
            pass

    # ------------------------------------------------------------------
    def delete(self, conversation_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "DELETE FROM conversations WHERE conversation_id = ?;",
                (conversation_id,),
            )

    def delete_all(self) -> int:
        with self._db.transaction() as conn:
            cur = conn.execute("DELETE FROM conversations;")
            return cur.rowcount or 0


# ----------------------------------------------------------------------
def _row_to_conversation(row) -> Conversation:
    try:
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
    except json.JSONDecodeError:
        meta = {}
    return Conversation(
        conversation_id=row["conversation_id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        archived=bool(row["archived"]),
        metadata=meta,
    )