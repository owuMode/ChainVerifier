# memory/manager.py
"""
MemoryManager — the single entry point for long-term memory.

Retrieval design:
  * Keyword search runs FIRST and is the primary path.
  * Vector search runs SECOND, only if the embedding service is
    available AND returns a result.
  * Short messages skip the embedding call entirely.

Phase 3 additions:
  * forget_by_query() — archive ALL matching memories (up to limit).
  * update_by_query() — replace the best-matching memory's content.
  * _find_best_matches() — hybrid keyword + vector lookup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from applog.logger import get_logger
from memory.embeddings import EmbeddingService, cosine_similarity
from memory.injector import build_memory_block
from memory.novelty import is_worth_extracting, tokenize
from memory.policies import DEFAULT_LIMITS, MemoryLimits, is_worth_storing
from memory.repositories import (
    ALLOWED_KINDS,
    ALLOWED_SOURCES,
    Memory,
    MemoryRepository,
    _tokenize,
)

log = get_logger("memory.manager")


_SHORT_MESSAGE_WORDS = 3


@dataclass(frozen=True)
class RankedMemory:
    memory: Memory
    vector_score: float
    keyword_score: float
    final_score: float


class MemoryManager:
    def __init__(
        self,
        repo: MemoryRepository,
        *,
        limits: MemoryLimits = DEFAULT_LIMITS,
        user_id: str = "default",
        embedding_service: Optional[EmbeddingService] = None,
    ) -> None:
        self._repo = repo
        self._limits = limits
        self._user_id = user_id
        self._embedder = embedding_service

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    def remember(
        self,
        content: str,
        *,
        kind: str = "fact",
        summary: str = "",
        confidence: float = 0.75,
        importance: int = 3,
        source: str = "explicit",
        source_conversation_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        expires_at: Optional[str] = None,
        metadata: Optional[dict] = None,
        dedupe: bool = True,
        embed: bool = True,
    ) -> Optional[Memory]:
        content = (content or "").strip()
        if not content:
            return None

        if kind not in ALLOWED_KINDS:
            kind = "other"
        if source not in ALLOWED_SOURCES:
            source = "extracted"

        if not is_worth_storing(content=content, confidence=confidence, limits=self._limits):
            log.info(
                "memory rejected by policy",
                extra={"kind": kind, "len": len(content), "confidence": confidence},
            )
            return None

        if dedupe and self._is_duplicate(content, kind):
            log.info("memory deduped", extra={"kind": kind, "len": len(content)})
            return None

        if tags is None:
            tags = _derive_tags(content)

        mem = Memory(
            memory_id="",
            user_id=self._user_id,
            kind=kind,
            content=content,
            summary=summary or _make_summary(content),
            confidence=float(confidence),
            importance=int(importance),
            source=source,
            source_conversation_id=source_conversation_id,
            source_message_id=source_message_id,
            tags=tags,
            expires_at=expires_at,
            metadata=metadata or {},
        )
        stored = self._repo.create(mem)
        log.info(
            "memory stored",
            extra={
                "memory_id": stored.memory_id,
                "kind": stored.kind,
                "importance": stored.importance,
                "source": stored.source,
            },
        )

        if embed:
            self._try_embed_one(stored)
        return stored

    def remember_extracted(
        self,
        extracted_list,
        *,
        source_conversation_id: Optional[str] = None,
    ) -> list[Memory]:
        stored: list[Memory] = []
        for e in extracted_list:
            m = self.remember(
                e.content,
                kind=e.kind,
                confidence=e.confidence,
                importance=e.importance,
                source="extracted",
                source_conversation_id=source_conversation_id,
                tags=list(e.tags),
                dedupe=True,
                embed=False,
            )
            if m is not None:
                stored.append(m)

        if stored:
            self._batch_embed(stored)
        return stored

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def recall(
        self,
        query: str,
        *,
        top_k: Optional[int] = None,
        kinds: Optional[list[str]] = None,
        touch_usage: bool = True,
    ) -> list[Memory]:
        ranked = self.recall_ranked(query, top_k=top_k, kinds=kinds)
        results = [r.memory for r in ranked]

        if touch_usage and results:
            try:
                self._repo.touch_usage([m.memory_id for m in results])
            except Exception:
                log.exception("touch_usage failed")

        log.info(
            "memory recall",
            extra={"query_len": len(query or ""), "returned": len(results)},
        )
        return results

    def recall_ranked(
        self,
        query: str,
        *,
        top_k: Optional[int] = None,
        kinds: Optional[list[str]] = None,
    ) -> list[RankedMemory]:
        k = int(top_k or self._limits.recall_top_k)
        if k <= 0 or not query or not query.strip():
            return []

        # ---- 1. Keyword search (PRIMARY) -----------------------------
        keyword_scores: dict[str, float] = {}
        kw_tokens = _tokenize(query)
        if kw_tokens:
            kw_mems = self._repo.search_keyword(
                query, user_id=self._user_id, limit=self._limits.keyword_top_k
            )
            for mem in kw_mems:
                if kinds and mem.kind not in kinds:
                    continue
                keyword_scores[mem.memory_id] = _keyword_overlap_score(kw_tokens, mem)

        # ---- 2. Vector search (SECONDARY, conditional) ---------------
        vector_scores: dict[str, float] = {}

        query_words = len(query.split())
        if query_words < _SHORT_MESSAGE_WORDS:
            log.info("recall: short query, skipping embedding")
        elif self._embedder is not None:
            try:
                if self._embedder.is_available():
                    embedded = self._embedder.embed_text(query)
                    if embedded is not None:
                        import numpy as np
                        qarr = np.asarray(embedded.values, dtype=np.float32)
                        candidates = self._repo.list_with_embedding(
                            user_id=self._user_id,
                            provider=embedded.provider,
                            limit=self._limits.vector_top_k * 10,
                        )
                        for mem in candidates:
                            if kinds and mem.kind not in kinds:
                                continue
                            mvec = mem.vector()
                            if mvec is None:
                                continue
                            sim = cosine_similarity(qarr, mvec)
                            if sim >= self._limits.min_vector_score:
                                vector_scores[mem.memory_id] = sim
            except Exception:
                log.info("recall: embedding failed, using keyword only")

        # ---- 3. Merge -------------------------------------------------
        all_ids = set(vector_scores) | set(keyword_scores)

        if not all_ids:
            fallback = self._repo.list_recent(user_id=self._user_id, limit=k)
            return [
                RankedMemory(memory=m, vector_score=0.0, keyword_score=0.0, final_score=0.0)
                for m in fallback
            ]

        w_vec = self._limits.hybrid_weight_vector
        w_kw = self._limits.hybrid_weight_keyword

        ranked: list[RankedMemory] = []
        for mid in all_ids:
            mem = self._repo.get(mid)
            if mem is None or mem.is_archived() or mem.is_expired():
                continue
            vs = float(vector_scores.get(mid, 0.0))
            ks = float(keyword_scores.get(mid, 0.0))
            final = vs * w_vec + ks * w_kw + 0.001 * float(mem.importance)
            ranked.append(
                RankedMemory(
                    memory=mem,
                    vector_score=vs,
                    keyword_score=ks,
                    final_score=final,
                )
            )

        ranked.sort(key=lambda r: r.final_score, reverse=True)
        return ranked[:k]

    def recall_block(
        self,
        query: str,
        *,
        top_k: Optional[int] = None,
        max_chars: int = 1200,
    ) -> str:
        mems = self.recall(query, top_k=top_k)
        return build_memory_block(mems, max_chars=max_chars)

    def list_all(
        self,
        *,
        include_archived: bool = False,
        include_expired: bool = False,
        limit: int = 200,
    ) -> list[Memory]:
        return self._repo.list_recent(
            user_id=self._user_id,
            include_archived=include_archived,
            include_expired=include_expired,
            limit=limit,
        )

    def get(self, memory_id: str) -> Optional[Memory]:
        return self._repo.get(memory_id)

    def count(self, *, include_archived: bool = False) -> int:
        return self._repo.count(
            user_id=self._user_id, include_archived=include_archived
        )

    # ------------------------------------------------------------------
    # Mutate
    # ------------------------------------------------------------------
    def update(
        self,
        memory_id: str,
        *,
        content: Optional[str] = None,
        kind: Optional[str] = None,
        importance: Optional[int] = None,
        confidence: Optional[float] = None,
        tags: Optional[list[str]] = None,
    ) -> Optional[Memory]:
        mem = self._repo.get(memory_id)
        if mem is None:
            return None

        if content is not None:
            mem.content = content.strip()
            mem.summary = _make_summary(mem.content)
        if kind is not None and kind in ALLOWED_KINDS:
            mem.kind = kind
        if importance is not None:
            mem.importance = int(importance)
        if confidence is not None:
            mem.confidence = float(confidence)
        if tags is not None:
            mem.tags = list(tags)

        self._repo.update(mem)

        if content is not None:
            self._try_embed_one(mem)
        return mem

    def update_first_matching(
        self,
        *,
        search_text: str,
        new_content: str,
        new_kind: Optional[str] = None,
    ) -> Optional[Memory]:
        search_text = (search_text or "").strip()
        new_content = (new_content or "").strip()
        if not search_text or not new_content:
            return None

        candidates = self._repo.search_keyword(
            search_text, user_id=self._user_id, limit=10
        )
        if not candidates:
            return None

        best = candidates[0]
        return self.update(
            best.memory_id,
            content=new_content,
            kind=new_kind,
        )

    # ------------------------------------------------------------------
    # Intent-based commands
    # ------------------------------------------------------------------
    def forget_by_query(
        self,
        query: str,
        *,
        max_to_forget: int = 5,
    ) -> list[Memory]:
        """
        Find ALL memories matching `query` (keyword + vector) and
        archive them (up to max_to_forget).

        Returns the list of archived Memory objects.
        """
        query = (query or "").strip()
        if not query:
            return []

        candidates = self._find_best_matches(query, top_k=max_to_forget)
        if not candidates:
            return []

        archived: list[Memory] = []
        for mem in candidates:
            try:
                self._repo.archive(mem.memory_id)
                archived.append(mem)
            except Exception:
                log.exception(
                    "forget_by_query: archive failed",
                    extra={"memory_id": mem.memory_id},
                )

        log.info(
            "memory: forgot by query",
            extra={
                "query": query[:60],
                "count": len(archived),
                "ids": [m.memory_id for m in archived][:5],
            },
        )
        return archived

    def update_by_query(
        self,
        *,
        query: str,
        new_value: str,
        new_kind: Optional[str] = None,
    ) -> Optional[Memory]:
        """
        Find the best matching memory and replace its content.
        If no match, store as a fresh memory of the inferred kind.
        """
        query = (query or "").strip()
        new_value = (new_value or "").strip()
        if not new_value:
            return None

        candidates = self._find_best_matches(query, top_k=1) if query else []

        if candidates:
            best = candidates[0]
            updated = self.update(
                best.memory_id,
                content=new_value,
                kind=new_kind,
            )
            log.info(
                "memory: updated by query",
                extra={
                    "query": query[:60],
                    "memory_id": best.memory_id,
                },
            )
            return updated

        kind = new_kind or _infer_kind_from_text(query or new_value)
        return self.remember(
            new_value,
            kind=kind,
            source="explicit",
            confidence=0.95,
        )

    def forget(self, memory_id: str) -> bool:
        mem = self._repo.get(memory_id)
        if mem is None:
            return False
        self._repo.archive(memory_id)
        log.info("memory archived", extra={"memory_id": memory_id})
        return True

    def restore(self, memory_id: str) -> bool:
        mem = self._repo.get(memory_id)
        if mem is None:
            return False
        self._repo.unarchive(memory_id)
        log.info("memory restored", extra={"memory_id": memory_id})
        return True

    def forget_all(self) -> int:
        count = 0
        for m in self._repo.list_recent(
            user_id=self._user_id,
            include_archived=False,
            include_expired=True,
            limit=10000,
        ):
            self._repo.archive(m.memory_id)
            count += 1
        log.info("all memories archived", extra={"count": count})
        return count

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------
    def purge_expired(self) -> int:
        n = self._repo.purge_expired(user_id=self._user_id)
        if n:
            log.info("expired memories purged", extra={"count": n})
        return n

    def reembed_all(self) -> int:
        if self._embedder is None:
            return 0
        try:
            if not self._embedder.is_available():
                return 0
        except Exception:
            return 0

        mems = self._repo.list_recent(
            user_id=self._user_id,
            include_archived=False,
            include_expired=True,
            limit=10000,
        )
        if not mems:
            return 0

        batch_size = max(1, int(self._limits.embedding_batch_size))
        done = 0
        for i in range(0, len(mems), batch_size):
            chunk = mems[i:i + batch_size]
            texts = tuple(m.content for m in chunk)
            try:
                vecs = self._embedder.embed_texts(texts)
            except Exception:
                continue
            if len(vecs) != len(chunk):
                continue
            for mem, ev in zip(chunk, vecs):
                try:
                    self._repo.set_embedding(
                        mem.memory_id,
                        values=ev.values,
                        provider=ev.provider,
                        model=ev.model,
                    )
                    done += 1
                except Exception:
                    pass
        log.info("reembed complete", extra={"count": done})
        return done

    def has_novel_content(
        self,
        *,
        conversation_tokens: set[str],
        min_new_tokens: int = 3,
    ) -> bool:
        known: set[str] = set()
        try:
            for m in self._repo.list_recent(user_id=self._user_id, limit=500):
                known |= tokenize(m.content)
        except Exception:
            pass
        return is_worth_extracting(
            conversation_tokens=conversation_tokens,
            known_tokens=known,
            min_new_tokens=min_new_tokens,
        )

    # ------------------------------------------------------------------
    # Consolidation
    # ------------------------------------------------------------------
    def consolidate(
        self,
        *,
        consolidator,
        model: str,
        dry_run: bool = False,
    ) -> dict:
        stats = {
            "groups_found": 0,
            "groups_merged": 0,
            "memories_archived": 0,
            "memories_created": 0,
            "errors": 0,
        }

        if consolidator is None:
            return stats

        try:
            all_mems = self._repo.list_recent(
                user_id=self._user_id,
                include_archived=False,
                include_expired=False,
                limit=2000,
            )
        except Exception:
            log.exception("consolidate: could not list memories")
            stats["errors"] += 1
            return stats

        groups = consolidator.find_merge_groups(all_mems)
        stats["groups_found"] = len(groups)

        for group in groups:
            try:
                result = consolidator.merge_group(group, model=model)
            except Exception:
                log.exception("consolidate: merge_group failed")
                stats["errors"] += 1
                continue

            if result is None or not result.is_valid():
                continue

            if dry_run:
                stats["groups_merged"] += 1
                continue

            source_ids = [m.memory_id for m in group.memories]

            try:
                merged_importance = max(
                    int(result.importance),
                    max(m.importance for m in group.memories),
                )
                merged = self.remember(
                    result.content,
                    kind=group.kind,
                    confidence=result.confidence,
                    importance=merged_importance,
                    source="extracted",
                    tags=_derive_tags(result.content),
                    metadata={
                        "consolidated_from": source_ids,
                        "consolidation_reason": result.reason,
                    },
                    dedupe=False,
                    embed=True,
                )
                if merged is None:
                    stats["errors"] += 1
                    continue
                stats["memories_created"] += 1
            except Exception:
                log.exception("consolidate: failed to store merged memory")
                stats["errors"] += 1
                continue

            for m in group.memories:
                try:
                    self._repo.archive(m.memory_id)
                    stats["memories_archived"] += 1
                except Exception:
                    log.exception(
                        "consolidate: archive failed",
                        extra={"memory_id": m.memory_id},
                    )

            stats["groups_merged"] += 1

        log.info("consolidation complete", extra=stats)
        return stats

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _is_duplicate(self, content: str, kind: str) -> bool:
        needle = content.strip().lower()
        for existing in self._repo.list_by_kind(
            kind, user_id=self._user_id, limit=200
        ):
            if existing.content.strip().lower() == needle:
                return True
        return False

    def _try_embed_one(self, mem: Memory) -> None:
        if self._embedder is None:
            return
        try:
            if not self._embedder.is_available():
                return
        except Exception:
            return
        try:
            ev = self._embedder.embed_text(mem.content)
        except Exception:
            return
        if ev is None:
            return
        try:
            self._repo.set_embedding(
                mem.memory_id,
                values=ev.values,
                provider=ev.provider,
                model=ev.model,
            )
            mem.embedding_provider = ev.provider
            mem.embedding_model = ev.model
            mem.embedding_dim = ev.dim
        except Exception:
            pass

    def _batch_embed(self, mems: list[Memory]) -> None:
        if not mems or self._embedder is None:
            return
        try:
            if not self._embedder.is_available():
                return
        except Exception:
            return

        batch_size = max(1, int(self._limits.embedding_batch_size))
        for i in range(0, len(mems), batch_size):
            chunk = mems[i:i + batch_size]
            texts = tuple(m.content for m in chunk)
            try:
                vecs = self._embedder.embed_texts(texts)
            except Exception:
                continue
            if len(vecs) != len(chunk):
                continue
            for mem, ev in zip(chunk, vecs):
                try:
                    self._repo.set_embedding(
                        mem.memory_id,
                        values=ev.values,
                        provider=ev.provider,
                        model=ev.model,
                    )
                except Exception:
                    pass

    def _find_best_matches(
        self, query: str, *, top_k: int = 5
    ) -> list[Memory]:
        """
        Return the top-k memories most similar to `query`.

        Uses keyword search first, vector search second. Never raises.
        """
        query = (query or "").strip()
        if not query:
            return []

        try:
            kw = self._repo.search_keyword(
                query, user_id=self._user_id, limit=top_k * 2
            )
        except Exception:
            kw = []

        vec: list[Memory] = []
        try:
            if self._embedder is not None and self._embedder.is_available():
                embedded = self._embedder.embed_text(query)
                if embedded is not None:
                    import numpy as np
                    qarr = np.asarray(embedded.values, dtype=np.float32)
                    rows = self._repo.list_with_embedding(
                        user_id=self._user_id,
                        provider=embedded.provider,
                        limit=200,
                    )
                    scored: list[tuple[float, Memory]] = []
                    for m in rows:
                        mvec = m.vector()
                        if mvec is None:
                            continue
                        sim = cosine_similarity(qarr, mvec)
                        if sim >= 0.35:
                            scored.append((sim, m))
                    scored.sort(key=lambda t: t[0], reverse=True)
                    vec = [m for _, m in scored[:top_k]]
        except Exception:
            vec = []

        seen: set[str] = set()
        merged: list[Memory] = []
        for m in kw:
            if m.memory_id not in seen:
                merged.append(m)
                seen.add(m.memory_id)
        for m in vec:
            if m.memory_id not in seen:
                merged.append(m)
                seen.add(m.memory_id)

        return merged[:top_k]


# ----------------------------------------------------------------------
# Content helpers
# ----------------------------------------------------------------------
def _make_summary(content: str, *, max_len: int = 120) -> str:
    text = " ".join(content.split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _derive_tags(content: str, *, max_tags: int = 6) -> list[str]:
    tokens = _tokenize(content)
    seen: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.append(t)
        if len(seen) >= max_tags:
            break
    return seen


def _keyword_overlap_score(query_tokens: list[str], mem: Memory) -> float:
    if not query_tokens:
        return 0.0
    haystack = " ".join(
        [mem.content or "", mem.summary or "", " ".join(mem.tags or [])]
    ).lower()
    if not haystack:
        return 0.0
    hits = sum(1 for t in query_tokens if t in haystack)
    return min(1.0, hits / float(len(query_tokens)))


def _infer_kind_from_text(text: str) -> str:
    """Small heuristic for kind inference."""
    low = (text or "").lower()
    if "name" in low or "naam" in low:
        return "identity"
    if any(k in low for k in ("prefer", "pasand", "like", "love", "favourite")):
        return "preference"
    if any(k in low for k in ("goal", "want to", "karna chahta")):
        return "goal"
    return "fact"