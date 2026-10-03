# memory/repositories.py
"""
MemoryRepository — persistence for long-term memories.

Owns all SQL for the `memories` table.

Design:
  * Soft delete: rows are never removed, only archived.
  * Embeddings stored as float32 BLOB (little-endian).
  * Vector search is done in Python after loading candidate rows; the
    DB only filters by provider to keep the row count small.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np

from database.manager import DatabaseManager
from memory.embeddings import cosine_similarity, from_blob, to_blob


# ----------------------------------------------------------------------
# Kinds
# ----------------------------------------------------------------------
ALLOWED_KINDS = frozenset({
    "identity",
    "preference",
    "fact",
    "context",
    "relationship",
    "goal",
    "habit",
    "constraint",
    "skill",
    "interest",
    "opinion",
    "event",
    "other",
})

ALLOWED_SOURCES = frozenset({
    "explicit",
    "extracted",
    "imported",
})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------------
# Model
# ----------------------------------------------------------------------
@dataclass
class Memory:
    memory_id: str
    user_id: str
    kind: str
    content: str
    summary: str = ""
    confidence: float = 0.75
    importance: int = 3
    source: str = "extracted"
    source_conversation_id: Optional[str] = None
    source_message_id: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    expires_at: Optional[str] = None
    archived_at: Optional[str] = None
    use_count: int = 0
    last_used_at: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    # Embedding fields (Phase 4d)
    embedding: Optional[bytes] = None
    embedding_provider: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_dim: Optional[int] = None
    embedding_updated_at: Optional[str] = None

    def is_archived(self) -> bool:
        return bool(self.archived_at)

    def is_expired(self, now_iso: Optional[str] = None) -> bool:
        if not self.expires_at:
            return False
        now = now_iso or _utc_now()
        return self.expires_at <= now

    def has_embedding(self) -> bool:
        return bool(self.embedding) and bool(self.embedding_provider)

    def vector(self) -> Optional[np.ndarray]:
        if not self.has_embedding():
            return None
        try:
            return from_blob(self.embedding, int(self.embedding_dim or 0))
        except Exception:
            return None


# ----------------------------------------------------------------------
# Repository
# ----------------------------------------------------------------------
class MemoryRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------
    def create(self, memory: Memory) -> Memory:
        if not memory.memory_id:
            memory.memory_id = str(uuid.uuid4())
        if not memory.kind:
            memory.kind = "other"
        if memory.kind not in ALLOWED_KINDS:
            raise ValueError(f"invalid memory kind: {memory.kind!r}")
        if memory.source not in ALLOWED_SOURCES:
            memory.source = "extracted"
        memory.importance = max(1, min(5, int(memory.importance)))
        memory.confidence = max(0.0, min(1.0, float(memory.confidence)))

        now = _utc_now()
        memory.created_at = memory.created_at or now
        memory.updated_at = now

        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO memories (
                    memory_id, user_id, kind, content, summary,
                    confidence, importance, source,
                    source_conversation_id, source_message_id,
                    tags, expires_at, archived_at,
                    use_count, last_used_at,
                    created_at, updated_at, metadata,
                    embedding, embedding_provider, embedding_model,
                    embedding_dim, embedding_updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    memory.memory_id,
                    memory.user_id or "default",
                    memory.kind,
                    memory.content,
                    memory.summary or "",
                    float(memory.confidence),
                    int(memory.importance),
                    memory.source,
                    memory.source_conversation_id,
                    memory.source_message_id,
                    json.dumps(list(memory.tags or []), ensure_ascii=False),
                    memory.expires_at,
                    memory.archived_at,
                    int(memory.use_count or 0),
                    memory.last_used_at,
                    memory.created_at,
                    memory.updated_at,
                    json.dumps(memory.metadata or {}, ensure_ascii=False),
                    memory.embedding,
                    memory.embedding_provider,
                    memory.embedding_model,
                    memory.embedding_dim,
                    memory.embedding_updated_at,
                ),
            )
        return memory

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------
    def update(self, memory: Memory) -> None:
        memory.importance = max(1, min(5, int(memory.importance)))
        memory.confidence = max(0.0, min(1.0, float(memory.confidence)))
        memory.updated_at = _utc_now()

        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE memories SET
                    kind = ?,
                    content = ?,
                    summary = ?,
                    confidence = ?,
                    importance = ?,
                    tags = ?,
                    expires_at = ?,
                    archived_at = ?,
                    metadata = ?,
                    embedding = ?,
                    embedding_provider = ?,
                    embedding_model = ?,
                    embedding_dim = ?,
                    embedding_updated_at = ?,
                    updated_at = ?
                WHERE memory_id = ?;
                """,
                (
                    memory.kind,
                    memory.content,
                    memory.summary or "",
                    float(memory.confidence),
                    int(memory.importance),
                    json.dumps(list(memory.tags or []), ensure_ascii=False),
                    memory.expires_at,
                    memory.archived_at,
                    json.dumps(memory.metadata or {}, ensure_ascii=False),
                    memory.embedding,
                    memory.embedding_provider,
                    memory.embedding_model,
                    memory.embedding_dim,
                    memory.embedding_updated_at,
                    memory.updated_at,
                    memory.memory_id,
                ),
            )

    def set_embedding(
        self,
        memory_id: str,
        *,
        values: tuple[float, ...],
        provider: str,
        model: str,
    ) -> None:
        blob = to_blob(values)
        dim = len(values)
        now = _utc_now()
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE memories SET
                    embedding = ?,
                    embedding_provider = ?,
                    embedding_model = ?,
                    embedding_dim = ?,
                    embedding_updated_at = ?,
                    updated_at = ?
                WHERE memory_id = ?;
                """,
                (blob, provider, model, dim, now, now, memory_id),
            )

    def clear_embeddings(self, *, user_id: str = "default") -> int:
        now = _utc_now()
        with self._db.transaction() as conn:
            cur = conn.execute(
                """
                UPDATE memories SET
                    embedding = NULL,
                    embedding_provider = NULL,
                    embedding_model = NULL,
                    embedding_dim = NULL,
                    embedding_updated_at = NULL,
                    updated_at = ?
                WHERE user_id = ?;
                """,
                (now, user_id),
            )
            return cur.rowcount or 0

    def touch_usage(self, memory_ids: list[str]) -> None:
        if not memory_ids:
            return
        now = _utc_now()
        with self._db.transaction() as conn:
            for mid in memory_ids:
                conn.execute(
                    """
                    UPDATE memories
                    SET use_count = use_count + 1, last_used_at = ?
                    WHERE memory_id = ?;
                    """,
                    (now, mid),
                )

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    def archive(self, memory_id: str) -> None:
        now = _utc_now()
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE memories SET archived_at = ?, updated_at = ? WHERE memory_id = ?;",
                (now, now, memory_id),
            )

    def unarchive(self, memory_id: str) -> None:
        now = _utc_now()
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE memories SET archived_at = NULL, updated_at = ? WHERE memory_id = ?;",
                (now, memory_id),
            )

    def hard_delete(self, memory_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM memories WHERE memory_id = ?;", (memory_id,))

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def get(self, memory_id: str) -> Optional[Memory]:
        row = self._db.connection.execute(
            "SELECT * FROM memories WHERE memory_id = ?;",
            (memory_id,),
        ).fetchone()
        return _row_to_memory(row) if row else None

    def list_recent(
        self,
        *,
        user_id: str = "default",
        include_archived: bool = False,
        include_expired: bool = False,
        limit: int = 200,
    ) -> list[Memory]:
        sql = "SELECT * FROM memories WHERE user_id = ?"
        params: list[Any] = [user_id]

        if not include_archived:
            sql += " AND archived_at IS NULL"
        if not include_expired:
            sql += " AND (expires_at IS NULL OR expires_at > ?)"
            params.append(_utc_now())

        sql += " ORDER BY created_at DESC LIMIT ?;"
        params.append(int(limit))

        rows = self._db.connection.execute(sql, params).fetchall()
        return [_row_to_memory(r) for r in rows]

    def list_by_kind(
        self,
        kind: str,
        *,
        user_id: str = "default",
        limit: int = 100,
    ) -> list[Memory]:
        rows = self._db.connection.execute(
            """
            SELECT * FROM memories
            WHERE user_id = ? AND kind = ?
              AND archived_at IS NULL
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY created_at DESC
            LIMIT ?;
            """,
            (user_id, kind, _utc_now(), int(limit)),
        ).fetchall()
        return [_row_to_memory(r) for r in rows]

    def search_keyword(
        self,
        query: str,
        *,
        user_id: str = "default",
        limit: int = 20,
    ) -> list[Memory]:
        tokens = _tokenize(query)
        if not tokens:
            return []

        like_clauses = []
        params: list[Any] = [user_id, _utc_now()]
        for tok in tokens:
            pattern = f"%{tok}%"
            like_clauses.append(
                "(LOWER(content) LIKE ? OR LOWER(summary) LIKE ? OR LOWER(tags) LIKE ?)"
            )
            params.extend([pattern, pattern, pattern])

        where_keywords = " OR ".join(like_clauses)

        sql = f"""
            SELECT * FROM memories
            WHERE user_id = ?
              AND archived_at IS NULL
              AND (expires_at IS NULL OR expires_at > ?)
              AND ({where_keywords})
            ORDER BY importance DESC, created_at DESC
            LIMIT ?;
        """
        params.append(int(limit))

        rows = self._db.connection.execute(sql, params).fetchall()
        return [_row_to_memory(r) for r in rows]

    def list_with_embedding(
        self,
        *,
        user_id: str = "default",
        provider: str,
        limit: int = 2000,
    ) -> list[Memory]:
        rows = self._db.connection.execute(
            """
            SELECT * FROM memories
            WHERE user_id = ?
              AND archived_at IS NULL
              AND (expires_at IS NULL OR expires_at > ?)
              AND embedding IS NOT NULL
              AND embedding_provider = ?
            ORDER BY importance DESC, created_at DESC
            LIMIT ?;
            """,
            (user_id, _utc_now(), provider, int(limit)),
        ).fetchall()
        return [_row_to_memory(r) for r in rows]

    def count(
        self,
        *,
        user_id: str = "default",
        include_archived: bool = False,
    ) -> int:
        sql = "SELECT COUNT(*) AS n FROM memories WHERE user_id = ?"
        params: list[Any] = [user_id]
        if not include_archived:
            sql += " AND archived_at IS NULL"
        row = self._db.connection.execute(sql, params).fetchone()
        return int(row["n"]) if row else 0

    def count_with_embedding(
        self,
        *,
        user_id: str = "default",
        provider: Optional[str] = None,
    ) -> int:
        if provider:
            row = self._db.connection.execute(
                """
                SELECT COUNT(*) AS n FROM memories
                WHERE user_id = ? AND embedding IS NOT NULL AND embedding_provider = ?;
                """,
                (user_id, provider),
            ).fetchone()
        else:
            row = self._db.connection.execute(
                """
                SELECT COUNT(*) AS n FROM memories
                WHERE user_id = ? AND embedding IS NOT NULL;
                """,
                (user_id,),
            ).fetchone()
        return int(row["n"]) if row else 0

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------
    def purge_expired(self, *, user_id: str = "default") -> int:
        now = _utc_now()
        with self._db.transaction() as conn:
            cur = conn.execute(
                """
                UPDATE memories
                SET archived_at = ?, updated_at = ?
                WHERE user_id = ?
                  AND archived_at IS NULL
                  AND expires_at IS NOT NULL
                  AND expires_at <= ?;
                """,
                (now, now, user_id, now),
            )
            return cur.rowcount or 0


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _row_to_memory(row) -> Memory:
    try:
        tags = json.loads(row["tags"]) if row["tags"] else []
        if not isinstance(tags, list):
            tags = []
    except json.JSONDecodeError:
        tags = []

    try:
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        if not isinstance(meta, dict):
            meta = {}
    except json.JSONDecodeError:
        meta = {}

    def _col(name):
        try:
            return row[name]
        except (KeyError, IndexError):
            return None

    return Memory(
        memory_id=row["memory_id"],
        user_id=row["user_id"],
        kind=row["kind"],
        content=row["content"],
        summary=row["summary"] or "",
        confidence=float(row["confidence"] or 0.75),
        importance=int(row["importance"] or 3),
        source=row["source"] or "extracted",
        source_conversation_id=row["source_conversation_id"],
        source_message_id=row["source_message_id"],
        tags=tags,
        expires_at=row["expires_at"],
        archived_at=row["archived_at"],
        use_count=int(row["use_count"] or 0),
        last_used_at=row["last_used_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        metadata=meta,
        embedding=_col("embedding"),
        embedding_provider=_col("embedding_provider"),
        embedding_model=_col("embedding_model"),
        embedding_dim=_col("embedding_dim"),
        embedding_updated_at=_col("embedding_updated_at"),
    )


_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+", re.UNICODE)

_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "can", "of", "in", "on", "at", "to",
    "for", "with", "by", "from", "as", "and", "or", "but", "if", "then",
    "this", "that", "these", "those", "i", "you", "he", "she", "it", "we",
    "they", "my", "your", "his", "her", "its", "our", "their",
    # Common fillers that add noise to similarity.
    "very", "much", "lot", "lots", "really", "quite", "just", "only",
    "also", "too", "so", "such", "more", "most", "some", "any", "all",
    "no", "not", "yes", "ok", "okay",
})


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    return [
        t.lower() for t in _TOKEN_RE.findall(text)
        if len(t) >= 2 and t.lower() not in _STOPWORDS
    ]