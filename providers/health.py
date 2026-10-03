# providers/health.py
"""
ProviderHealth — tracks per-model health for the fallback router.

Design:
  * SQLite-backed (persistent across restarts).
  * A model that fails with a retryable error (429/503/timeout/network)
    enters COOLDOWN for N seconds.
  * A provider that returns 401/403 is marked INVALID until the user
    changes the key (we clear INVALID when we successfully use it
    again).
  * Never raises: on any DB error, the health check is a no-op.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from applog.logger import get_logger

log = get_logger("providers.health")


DEFAULT_COOLDOWN_S = 60


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_future(iso: Optional[str]) -> bool:
    if not iso:
        return False
    try:
        dt = datetime.fromisoformat(iso)
    except Exception:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt > datetime.now(timezone.utc)


class ProviderHealth:
    def __init__(self, db, *, cooldown_s: int = DEFAULT_COOLDOWN_S) -> None:
        self._db = db
        self._cooldown_s = int(cooldown_s)
        self._lock = threading.RLock()
        # In-memory fast cache so we don't hit the DB on every check.
        self._cache: dict[tuple[str, str], dict] = {}

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    def is_available(self, provider: str, model: str) -> bool:
        """
        True if this (provider, model) may be attempted.
        """
        with self._lock:
            entry = self._cache.get((provider, model))
        if entry is None:
            entry = self._load(provider, model)
        if entry is None:
            return True

        status = entry.get("status", "ok")
        if status == "invalid":
            return False
        if status == "cooldown":
            return not _is_future(entry.get("failed_until"))
        return True

    def provider_is_valid(self, provider: str) -> bool:
        """
        True if we have never seen an auth error for this provider.
        """
        try:
            with self._lock:
                row = self._db.connection.execute(
                    """
                    SELECT COUNT(*) AS n FROM provider_health
                    WHERE provider = ? AND status = 'invalid';
                    """,
                    (provider,),
                ).fetchone()
            return int(row["n"]) == 0 if row else True
        except Exception:
            return True

    # ------------------------------------------------------------------
    # Record outcomes
    # ------------------------------------------------------------------
    def record_success(self, provider: str, model: str) -> None:
        now = _utc_now()
        try:
            with self._lock:
                with self._db.transaction() as conn:
                    conn.execute(
                        """
                        INSERT INTO provider_health
                            (provider, model, status, reason,
                             failed_until, failure_count, success_count,
                             last_error_at, updated_at)
                        VALUES (?, ?, 'ok', '', NULL, 0, 1, NULL, ?)
                        ON CONFLICT(provider, model) DO UPDATE SET
                            status = 'ok',
                            reason = '',
                            failed_until = NULL,
                            success_count = provider_health.success_count + 1,
                            updated_at = excluded.updated_at;
                        """,
                        (provider, model, now),
                    )
                self._cache.pop((provider, model), None)
        except Exception:
            log.exception(
                "health: record_success failed",
                extra={"provider": provider, "model": model},
            )

    def record_failure(
        self,
        provider: str,
        model: str,
        *,
        reason: str,
        cooldown_s: Optional[int] = None,
    ) -> None:
        """
        Mark a model as unhealthy. If `cooldown_s` is None, uses the
        default cooldown.
        """
        cd = self._cooldown_s if cooldown_s is None else int(cooldown_s)
        until = (
            datetime.now(timezone.utc) + timedelta(seconds=cd)
        ).isoformat()
        now = _utc_now()
        try:
            with self._lock:
                with self._db.transaction() as conn:
                    conn.execute(
                        """
                        INSERT INTO provider_health
                            (provider, model, status, reason,
                             failed_until, failure_count, success_count,
                             last_error_at, updated_at)
                        VALUES (?, ?, 'cooldown', ?, ?, 1, 0, ?, ?)
                        ON CONFLICT(provider, model) DO UPDATE SET
                            status = 'cooldown',
                            reason = excluded.reason,
                            failed_until = excluded.failed_until,
                            failure_count = provider_health.failure_count + 1,
                            last_error_at = excluded.last_error_at,
                            updated_at = excluded.updated_at;
                        """,
                        (provider, model, reason[:200], until, now, now),
                    )
                self._cache.pop((provider, model), None)
        except Exception:
            log.exception(
                "health: record_failure failed",
                extra={"provider": provider, "model": model},
            )

    def record_auth_error(self, provider: str) -> None:
        """
        Mark every model for this provider as invalid.
        """
        now = _utc_now()
        try:
            with self._lock:
                with self._db.transaction() as conn:
                    # Upsert a single row per model we know about.
                    models = self._list_models_for_provider(provider)
                    if not models:
                        models = ["*"]
                    for model in models:
                        conn.execute(
                            """
                            INSERT INTO provider_health
                                (provider, model, status, reason,
                                 failed_until, failure_count, success_count,
                                 last_error_at, updated_at)
                            VALUES (?, ?, 'invalid', 'auth_error',
                                    NULL, 1, 0, ?, ?)
                            ON CONFLICT(provider, model) DO UPDATE SET
                                status = 'invalid',
                                reason = 'auth_error',
                                failed_until = NULL,
                                failure_count = provider_health.failure_count + 1,
                                last_error_at = excluded.last_error_at,
                                updated_at = excluded.updated_at;
                            """,
                            (provider, model, now, now),
                        )
                self._cache.clear()
        except Exception:
            log.exception("health: record_auth_error failed", extra={"provider": provider})

    def clear_provider(self, provider: str) -> None:
        """
        Reset all health state for a provider (used when the key changes).
        """
        try:
            with self._lock:
                with self._db.transaction() as conn:
                    conn.execute(
                        "DELETE FROM provider_health WHERE provider = ?;",
                        (provider,),
                    )
                self._cache.clear()
        except Exception:
            log.exception("health: clear_provider failed", extra={"provider": provider})

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def snapshot(self) -> dict:
        try:
            with self._lock:
                rows = self._db.connection.execute(
                    "SELECT * FROM provider_health;"
                ).fetchall()
            return {
                f"{r['provider']}::{r['model']}": {
                    "status": r["status"],
                    "reason": r["reason"],
                    "failed_until": r["failed_until"],
                    "failures": r["failure_count"],
                    "successes": r["success_count"],
                }
                for r in rows
            }
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _load(self, provider: str, model: str) -> Optional[dict]:
        try:
            with self._lock:
                row = self._db.connection.execute(
                    """
                    SELECT * FROM provider_health
                    WHERE provider = ? AND model = ?;
                    """,
                    (provider, model),
                ).fetchone()
        except Exception:
            return None
        if row is None:
            return None
        entry = {
            "status": row["status"],
            "reason": row["reason"],
            "failed_until": row["failed_until"],
        }
        with self._lock:
            self._cache[(provider, model)] = entry
        return entry

    def _list_models_for_provider(self, provider: str) -> list[str]:
        try:
            with self._lock:
                rows = self._db.connection.execute(
                    """
                    SELECT DISTINCT model FROM provider_health
                    WHERE provider = ?;
                    """,
                    (provider,),
                ).fetchall()
            return [r["model"] for r in rows]
        except Exception:
            return []