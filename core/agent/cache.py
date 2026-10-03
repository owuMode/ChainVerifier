# core/agent/cache.py
"""
Agent caches — cut API calls without hurting quality.

Two caches:
  * PlanCache       — sha256(goal + context + model) -> Plan
  * SynthesisCache  — sha256(goal + step_results + model) -> text

Design:
  * SQLite-backed, persistent across restarts.
  * TTL is enforced here (application-level).
  * Never raises: on any error, the cache is a no-op.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from applog.logger import get_logger

log = get_logger("core.agent.cache")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_json(payload: Any) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _is_fresh(created_at: str, ttl_seconds: int) -> bool:
    if not created_at or ttl_seconds <= 0:
        return False
    try:
        created = datetime.fromisoformat(created_at)
    except Exception:
        return False
    now = datetime.now(timezone.utc)
    return (now - created) <= timedelta(seconds=ttl_seconds)


# ----------------------------------------------------------------------
# Plan cache
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class CachedPlan:
    plan_dict: dict
    model: str
    created_at: str


class PlanCache:
    def __init__(self, db, *, ttl_seconds: int = 3600) -> None:
        self._db = db
        self._ttl = int(ttl_seconds)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    def make_key(
        self,
        *,
        goal: str,
        context_messages: Optional[list[dict[str, str]]],
        model: str,
    ) -> str:
        ctx_digest = _hash_json(context_messages or [])
        return _hash_json(
            {"goal": goal, "context": ctx_digest, "model": model}
        )

    # ------------------------------------------------------------------
    def get(
        self,
        *,
        goal: str,
        context_messages: Optional[list[dict[str, str]]],
        model: str,
    ) -> Optional[CachedPlan]:
        if self._ttl <= 0:
            return None
        key = self.make_key(
            goal=goal, context_messages=context_messages, model=model
        )
        try:
            with self._lock:
                row = self._db.connection.execute(
                    """
                    SELECT plan_json, model, created_at
                    FROM planner_cache
                    WHERE cache_key = ?;
                    """,
                    (key,),
                ).fetchone()
        except Exception:
            return None
        if row is None:
            return None
        if not _is_fresh(row["created_at"], self._ttl):
            return None
        try:
            plan_dict = json.loads(row["plan_json"])
        except Exception:
            return None
        self._touch(key)
        return CachedPlan(
            plan_dict=plan_dict,
            model=row["model"],
            created_at=row["created_at"],
        )

    # ------------------------------------------------------------------
    def put(
        self,
        *,
        goal: str,
        context_messages: Optional[list[dict[str, str]]],
        model: str,
        plan_dict: dict,
    ) -> None:
        if self._ttl <= 0:
            return
        key = self.make_key(
            goal=goal, context_messages=context_messages, model=model
        )
        now = _utc_now()
        try:
            with self._lock:
                with self._db.transaction() as conn:
                    conn.execute(
                        """
                        INSERT INTO planner_cache
                            (cache_key, goal, context_json, plan_json, model,
                             created_at, last_used_at, use_count)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                        ON CONFLICT(cache_key) DO UPDATE SET
                            plan_json = excluded.plan_json,
                            last_used_at = excluded.last_used_at,
                            use_count = planner_cache.use_count + 1;
                        """,
                        (
                            key,
                            goal[:2000],
                            json.dumps(
                                context_messages or [],
                                ensure_ascii=False,
                                default=str,
                            )[:8000],
                            json.dumps(plan_dict, ensure_ascii=False),
                            model,
                            now,
                            now,
                        ),
                    )
        except Exception:
            log.exception("planner cache put failed")

    def _touch(self, key: str) -> None:
        try:
            with self._lock:
                with self._db.transaction() as conn:
                    conn.execute(
                        """
                        UPDATE planner_cache
                        SET use_count = use_count + 1, last_used_at = ?
                        WHERE cache_key = ?;
                        """,
                        (_utc_now(), key),
                    )
        except Exception:
            pass

    def clear(self) -> int:
        try:
            with self._lock:
                with self._db.transaction() as conn:
                    cur = conn.execute("DELETE FROM planner_cache;")
                    return cur.rowcount or 0
        except Exception:
            return 0

    def prune(self, *, keep: int = 500) -> int:
        try:
            with self._lock:
                with self._db.transaction() as conn:
                    cur = conn.execute(
                        """
                        DELETE FROM planner_cache
                        WHERE cache_key NOT IN (
                            SELECT cache_key FROM planner_cache
                            ORDER BY last_used_at DESC
                            LIMIT ?
                        );
                        """,
                        (int(keep),),
                    )
                    return cur.rowcount or 0
        except Exception:
            return 0


# ----------------------------------------------------------------------
# Synthesis cache
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class CachedSynthesis:
    text: str
    model: str
    created_at: str


class SynthesisCache:
    def __init__(self, db, *, ttl_seconds: int = 3600) -> None:
        self._db = db
        self._ttl = int(ttl_seconds)
        self._lock = threading.RLock()

    def make_key(
        self,
        *,
        goal: str,
        step_results_digest: list[dict],
        model: str,
    ) -> str:
        return _hash_json(
            {"goal": goal, "results": step_results_digest, "model": model}
        )

    def get(
        self,
        *,
        goal: str,
        step_results_digest: list[dict],
        model: str,
    ) -> Optional[CachedSynthesis]:
        if self._ttl <= 0:
            return None
        key = self.make_key(
            goal=goal, step_results_digest=step_results_digest, model=model
        )
        try:
            with self._lock:
                row = self._db.connection.execute(
                    """
                    SELECT text, model, created_at
                    FROM synthesis_cache
                    WHERE cache_key = ?;
                    """,
                    (key,),
                ).fetchone()
        except Exception:
            return None
        if row is None:
            return None
        if not _is_fresh(row["created_at"], self._ttl):
            return None
        self._touch(key)
        return CachedSynthesis(
            text=row["text"],
            model=row["model"],
            created_at=row["created_at"],
        )

    def put(
        self,
        *,
        goal: str,
        step_results_digest: list[dict],
        model: str,
        text: str,
    ) -> None:
        if self._ttl <= 0 or not text:
            return
        key = self.make_key(
            goal=goal, step_results_digest=step_results_digest, model=model
        )
        now = _utc_now()
        try:
            with self._lock:
                with self._db.transaction() as conn:
                    conn.execute(
                        """
                        INSERT INTO synthesis_cache
                            (cache_key, goal, results_json, text, model,
                             created_at, last_used_at, use_count)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                        ON CONFLICT(cache_key) DO UPDATE SET
                            text = excluded.text,
                            last_used_at = excluded.last_used_at,
                            use_count = synthesis_cache.use_count + 1;
                        """,
                        (
                            key,
                            goal[:2000],
                            json.dumps(
                                step_results_digest,
                                ensure_ascii=False,
                                default=str,
                            )[:8000],
                            text[:8000],
                            model,
                            now,
                            now,
                        ),
                    )
        except Exception:
            log.exception("synthesis cache put failed")

    def _touch(self, key: str) -> None:
        try:
            with self._lock:
                with self._db.transaction() as conn:
                    conn.execute(
                        """
                        UPDATE synthesis_cache
                        SET use_count = use_count + 1, last_used_at = ?
                        WHERE cache_key = ?;
                        """,
                        (_utc_now(), key),
                    )
        except Exception:
            pass

    def clear(self) -> int:
        try:
            with self._lock:
                with self._db.transaction() as conn:
                    cur = conn.execute("DELETE FROM synthesis_cache;")
                    return cur.rowcount or 0
        except Exception:
            return 0

    def prune(self, *, keep: int = 500) -> int:
        try:
            with self._lock:
                with self._db.transaction() as conn:
                    cur = conn.execute(
                        """
                        DELETE FROM synthesis_cache
                        WHERE cache_key NOT IN (
                            SELECT cache_key FROM synthesis_cache
                            ORDER BY last_used_at DESC
                            LIMIT ?
                        );
                        """,
                        (int(keep),),
                    )
                    return cur.rowcount or 0
        except Exception:
            return 0