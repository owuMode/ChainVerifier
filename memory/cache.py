# memory/cache.py
"""
Local caches — cut API calls without hurting quality.

Two caches:
  * EmbeddingCache   — sha256(text) -> vector (BLOB)
  * ClassifierCache  — sha256(normalized_text) -> decision dict

Design:
  * SQLite-backed (persistent across restarts).
  * LRU-ish eviction based on last_used_at.
  * Never raises: on any error, the cache is a no-op.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from applog.logger import get_logger

log = get_logger("memory.cache")


# ----------------------------------------------------------------------
# In-memory LRU for the hot path (avoid a DB hit on every lookup)
# ----------------------------------------------------------------------
class _MemoryLRU:
    def __init__(self, max_size: int = 512) -> None:
        self._max = int(max_size)
        self._data: dict[str, Any] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            v = self._data.get(key)
            if v is None:
                return None
            try:
                self._order.remove(key)
            except ValueError:
                pass
            self._order.append(key)
            return v

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._data:
                try:
                    self._order.remove(key)
                except ValueError:
                    pass
            self._data[key] = value
            self._order.append(key)
            while len(self._order) > self._max:
                old = self._order.pop(0)
                self._data.pop(old, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._order.clear()


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_for_classifier(text: str) -> str:
    """
    Normalize a message so trivial variations share a cache entry.
    Lowercase, collapse whitespace, strip trailing punctuation.
    """
    s = (text or "").strip().lower()
    s = " ".join(s.split())
    s = s.rstrip(".!?")
    return s


# ----------------------------------------------------------------------
# Embedding cache
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class CachedEmbedding:
    values: tuple[float, ...]
    provider: str
    model: str
    dim: int


class EmbeddingCache:
    def __init__(self, db, *, memory_lru_size: int = 512) -> None:
        self._db = db
        self._lru = _MemoryLRU(max_size=memory_lru_size)

    def get(self, text: str, *, provider: str) -> Optional[CachedEmbedding]:
        if not text:
            return None
        key = _hash_text(text)
        # In-memory first
        mem_hit = self._lru.get(key)
        if mem_hit is not None and mem_hit.provider == provider:
            return mem_hit

        # DB
        try:
            row = self._db.connection.execute(
                """
                SELECT embedding, embedding_dim, provider, model
                FROM embedding_cache
                WHERE cache_key = ? AND provider = ?;
                """,
                (key, provider),
            ).fetchone()
        except Exception:
            return None

        if row is None:
            return None

        try:
            import numpy as np
            arr = np.frombuffer(row["embedding"], dtype=np.float32)
            values = tuple(float(x) for x in arr)
            ce = CachedEmbedding(
                values=values,
                provider=row["provider"],
                model=row["model"],
                dim=int(row["embedding_dim"]),
            )
            self._lru.put(key, ce)
            self._touch(key)
            return ce
        except Exception:
            return None

    def put(self, text: str, *, values: tuple[float, ...], provider: str, model: str) -> None:
        if not text or not values:
            return
        key = _hash_text(text)
        try:
            import numpy as np
            blob = np.asarray(values, dtype=np.float32).tobytes()
            dim = len(values)
        except Exception:
            return
        now = _utc_now()
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO embedding_cache
                        (cache_key, text, embedding, embedding_dim, provider, model, created_at, last_used_at, use_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        embedding = excluded.embedding,
                        embedding_dim = excluded.embedding_dim,
                        provider = excluded.provider,
                        model = excluded.model,
                        last_used_at = excluded.last_used_at,
                        use_count = embedding_cache.use_count + 1;
                    """,
                    (key, text[:500], blob, dim, provider, model, now, now),
                )
        except Exception:
            log.exception("embedding cache put failed")
            return

        self._lru.put(
            key,
            CachedEmbedding(values=values, provider=provider, model=model, dim=dim),
        )

    def _touch(self, key: str) -> None:
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    """
                    UPDATE embedding_cache
                    SET use_count = use_count + 1, last_used_at = ?
                    WHERE cache_key = ?;
                    """,
                    (_utc_now(), key),
                )
        except Exception:
            pass

    def size(self) -> int:
        try:
            row = self._db.connection.execute(
                "SELECT COUNT(*) AS n FROM embedding_cache;"
            ).fetchone()
            return int(row["n"]) if row else 0
        except Exception:
            return 0

    def clear(self) -> int:
        try:
            with self._db.transaction() as conn:
                cur = conn.execute("DELETE FROM embedding_cache;")
                n = cur.rowcount or 0
            self._lru.clear()
            return n
        except Exception:
            return 0

    def prune(self, *, keep: int = 2000) -> int:
        """
        Delete the least-recently-used rows to keep the table small.
        """
        try:
            with self._db.transaction() as conn:
                cur = conn.execute(
                    """
                    DELETE FROM embedding_cache
                    WHERE cache_key NOT IN (
                        SELECT cache_key FROM embedding_cache
                        ORDER BY COALESCE(last_used_at, created_at) DESC
                        LIMIT ?
                    );
                    """,
                    (int(keep),),
                )
                return cur.rowcount or 0
        except Exception:
            return 0


# ----------------------------------------------------------------------
# Classifier cache
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class CachedClassification:
    kind: str
    confidence: float
    reason: str


class ClassifierCache:
    def __init__(self, db, *, memory_lru_size: int = 512) -> None:
        self._db = db
        self._lru = _MemoryLRU(max_size=memory_lru_size)

    def get(self, message: str) -> Optional[CachedClassification]:
        if not message:
            return None
        key = _hash_text(_normalize_for_classifier(message))
        hit = self._lru.get(key)
        if hit is not None:
            return hit

        try:
            row = self._db.connection.execute(
                """
                SELECT kind, confidence, reason
                FROM classifier_cache
                WHERE cache_key = ?;
                """,
                (key,),
            ).fetchone()
        except Exception:
            return None

        if row is None:
            return None

        cc = CachedClassification(
            kind=row["kind"],
            confidence=float(row["confidence"] or 0.0),
            reason=row["reason"] or "",
        )
        self._lru.put(key, cc)
        self._touch(key)
        return cc

    def put(self, message: str, *, kind: str, confidence: float, reason: str) -> None:
        if not message or kind not in ("chat", "task"):
            return
        key = _hash_text(_normalize_for_classifier(message))
        now = _utc_now()
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO classifier_cache
                        (cache_key, kind, confidence, reason, created_at, last_used_at, use_count)
                    VALUES (?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        kind = excluded.kind,
                        confidence = excluded.confidence,
                        reason = excluded.reason,
                        last_used_at = excluded.last_used_at,
                        use_count = classifier_cache.use_count + 1;
                    """,
                    (key, kind, float(confidence), reason[:500], now, now),
                )
        except Exception:
            log.exception("classifier cache put failed")
            return

        self._lru.put(
            key,
            CachedClassification(kind=kind, confidence=float(confidence), reason=reason),
        )

    def _touch(self, key: str) -> None:
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    """
                    UPDATE classifier_cache
                    SET use_count = use_count + 1, last_used_at = ?
                    WHERE cache_key = ?;
                    """,
                    (_utc_now(), key),
                )
        except Exception:
            pass

    def size(self) -> int:
        try:
            row = self._db.connection.execute(
                "SELECT COUNT(*) AS n FROM classifier_cache;"
            ).fetchone()
            return int(row["n"]) if row else 0
        except Exception:
            return 0

    def clear(self) -> int:
        try:
            with self._db.transaction() as conn:
                cur = conn.execute("DELETE FROM classifier_cache;")
                n = cur.rowcount or 0
            self._lru.clear()
            return n
        except Exception:
            return 0