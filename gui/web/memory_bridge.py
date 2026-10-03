# gui/web/memory_bridge.py
"""
MemoryBridge — Python <-> JS boundary for the memory subsystem.

Phase 3 additions:
  * getStatsJson() — totals, embedded count, last-7-days count.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from applog.logger import get_logger

log = get_logger("gui.web.memory_bridge")


class MemoryBridge(QObject):
    memoryChanged = Signal()
    enabledChanged = Signal(bool)
    continuityChanged = Signal(bool)
    expanderChanged = Signal(bool)

    def __init__(
        self,
        *,
        memory_manager,
        config,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._memory = memory_manager
        self._config = config
        self._consolidator = None
        self._consolidator_model = None

    # ------------------------------------------------------------------
    # Master toggle
    # ------------------------------------------------------------------
    @Slot(result=bool)
    def isEnabled(self) -> bool:
        try:
            return bool(self._config.get("memory.enabled", True))
        except Exception:
            return True

    @Slot(bool, result=bool)
    def setEnabled(self, enabled: bool) -> bool:
        try:
            self._config.set("memory.enabled", bool(enabled))
        except Exception:
            log.exception("setEnabled failed")
            return False
        self.enabledChanged.emit(bool(enabled))
        log.info("memory enabled changed", extra={"enabled": bool(enabled)})
        return True

    # ------------------------------------------------------------------
    # Continuity toggle
    # ------------------------------------------------------------------
    @Slot(result=bool)
    def isContinuityEnabled(self) -> bool:
        try:
            return bool(self._config.get("memory.continuity.enabled", True))
        except Exception:
            return True

    @Slot(bool, result=bool)
    def setContinuityEnabled(self, enabled: bool) -> bool:
        try:
            self._config.set("memory.continuity.enabled", bool(enabled))
        except Exception:
            log.exception("setContinuityEnabled failed")
            return False
        self.continuityChanged.emit(bool(enabled))
        log.info("continuity enabled changed", extra={"enabled": bool(enabled)})
        return True

    # ------------------------------------------------------------------
    # Expander toggle
    # ------------------------------------------------------------------
    @Slot(result=bool)
    def isExpanderEnabled(self) -> bool:
        try:
            return bool(self._config.get("memory.expander.enabled", True))
        except Exception:
            return True

    @Slot(bool, result=bool)
    def setExpanderEnabled(self, enabled: bool) -> bool:
        try:
            self._config.set("memory.expander.enabled", bool(enabled))
        except Exception:
            log.exception("setExpanderEnabled failed")
            return False
        self.expanderChanged.emit(bool(enabled))
        log.info("expander enabled changed", extra={"enabled": bool(enabled)})
        return True

    # ------------------------------------------------------------------
    # Stats (dashboard)
    # ------------------------------------------------------------------
    @Slot(result=str)
    def getStatsJson(self) -> str:
        """
        Return memory statistics as JSON:
          {
            "total": int,
            "embedded": int,
            "recent_7d": int
          }
        """
        stats = {
            "total": 0,
            "embedded": 0,
            "recent_7d": 0,
        }
        if self._memory is None:
            return json.dumps(stats, ensure_ascii=False)

        try:
            stats["total"] = int(self._memory.count())
        except Exception:
            log.exception("getStatsJson: count failed")

        try:
            repo = getattr(self._memory, "_repo", None)
            if repo is not None:
                stats["embedded"] = int(repo.count_with_embedding())
        except Exception:
            log.exception("getStatsJson: count_with_embedding failed")

        try:
            items = self._memory.list_all(limit=2000)
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            recent = 0
            for m in items:
                try:
                    created = datetime.fromisoformat(m.created_at)
                except Exception:
                    continue
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created >= cutoff:
                    recent += 1
            stats["recent_7d"] = recent
        except Exception:
            log.exception("getStatsJson: recent count failed")

        return json.dumps(stats, ensure_ascii=False)

    # ------------------------------------------------------------------
    # List / search / count
    # ------------------------------------------------------------------
    @Slot(str, result=str)
    def listJson(self, kind_filter: str) -> str:
        try:
            items = self._memory.list_all(limit=500)
        except Exception:
            log.exception("listJson failed")
            return "[]"

        k = str(kind_filter or "").strip().lower()
        if k:
            items = [m for m in items if m.kind == k]

        payload = [_memory_to_dict(m) for m in items]
        return json.dumps(payload, ensure_ascii=False)

    @Slot(str, result=str)
    def searchJson(self, query: str) -> str:
        try:
            items = self._memory.recall(query, top_k=50, touch_usage=False)
        except Exception:
            log.exception("searchJson failed")
            return "[]"
        payload = [_memory_to_dict(m) for m in items]
        return json.dumps(payload, ensure_ascii=False)

    @Slot(result=int)
    def count(self) -> int:
        try:
            return int(self._memory.count())
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Mutate
    # ------------------------------------------------------------------
    @Slot(str, str, int, result=str)
    def remember(self, content: str, kind: str, importance: int) -> str:
        try:
            m = self._memory.remember(
                content,
                kind=kind or "fact",
                importance=max(1, min(5, int(importance or 3))),
                source="explicit",
                confidence=0.95,
            )
        except Exception:
            log.exception("remember failed")
            return ""
        if m is None:
            return ""
        self.memoryChanged.emit()
        return json.dumps(_memory_to_dict(m), ensure_ascii=False)

    @Slot(str, result=bool)
    def forget(self, memory_id: str) -> bool:
        try:
            ok = self._memory.forget(memory_id)
        except Exception:
            log.exception("forget failed")
            return False
        if ok:
            self.memoryChanged.emit()
        return bool(ok)

    @Slot(str, result=bool)
    def restore(self, memory_id: str) -> bool:
        try:
            ok = self._memory.restore(memory_id)
        except Exception:
            log.exception("restore failed")
            return False
        if ok:
            self.memoryChanged.emit()
        return bool(ok)

    @Slot(str, str, result=bool)
    def updateContent(self, memory_id: str, content: str) -> bool:
        try:
            m = self._memory.update(memory_id, content=content)
        except Exception:
            log.exception("updateContent failed")
            return False
        if m is not None:
            self.memoryChanged.emit()
            return True
        return False

    @Slot(str, str, result=bool)
    def updateByMatch(self, search_text: str, new_content: str) -> bool:
        try:
            m = self._memory.update_first_matching(
                search_text=search_text,
                new_content=new_content,
            )
            if m is not None:
                self.memoryChanged.emit()
                return True
            return False
        except Exception:
            log.exception("updateByMatch failed")
            return False

    @Slot(result=int)
    def clearAll(self) -> int:
        try:
            n = self._memory.forget_all()
        except Exception:
            log.exception("clearAll failed")
            return 0
        self.memoryChanged.emit()
        return int(n)

    @Slot(result=int)
    def reembedAll(self) -> int:
        try:
            return int(self._memory.reembed_all())
        except Exception:
            log.exception("reembedAll failed")
            return 0

    # ------------------------------------------------------------------
    # Consolidation
    # ------------------------------------------------------------------
    def set_consolidator(self, consolidator, model: str) -> None:
        self._consolidator = consolidator
        self._consolidator_model = model

    @Slot(result=str)
    def consolidate(self) -> str:
        if self._consolidator is None or not self._consolidator_model:
            log.info("consolidate: no consolidator configured")
            return json.dumps({
                "groups_found": 0,
                "groups_merged": 0,
                "memories_archived": 0,
                "memories_created": 0,
                "errors": 1,
                "reason": "consolidator not configured",
            })

        try:
            stats = self._memory.consolidate(
                consolidator=self._consolidator,
                model=self._consolidator_model,
                dry_run=False,
            )
        except Exception:
            log.exception("consolidate failed")
            return json.dumps({
                "groups_found": 0,
                "groups_merged": 0,
                "memories_archived": 0,
                "memories_created": 0,
                "errors": 1,
                "reason": "exception",
            })

        self.memoryChanged.emit()
        return json.dumps(stats, ensure_ascii=False)


def _memory_to_dict(m) -> dict:
    return {
        "memory_id": m.memory_id,
        "kind": m.kind,
        "content": m.content,
        "summary": m.summary,
        "importance": m.importance,
        "confidence": m.confidence,
        "source": m.source,
        "tags": list(m.tags or []),
        "use_count": m.use_count,
        "created_at": m.created_at,
        "updated_at": m.updated_at,
        "archived_at": m.archived_at,
        "last_used_at": m.last_used_at,
    }