# memory/consolidator.py
"""
MemoryConsolidator — merge similar memories into one canonical memory.

Design:
  * Pure function for grouping; LLM call for merging.
  * Never raises. On any failure, returns an empty result.
  * Groups memories by kind, then by vector similarity OR keyword
    overlap. Only groups with 2+ members are merged.
  * Originals are archived (soft delete) via the manager.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from applog.logger import get_logger
from memory.repositories import Memory, MemoryRepository, _tokenize
from prompts.manager import PromptManager
from providers.base.models import ChatMessage, ChatRequest, Role
from providers.base.provider import AIProvider, ProviderError
from security.validation import validate

log = get_logger("memory.consolidator")


_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "importance": {"type": "integer", "minimum": 1, "maximum": 5},
        "reason": {"type": "string"},
    },
    "required": ["content"],
}


@dataclass(frozen=True)
class MergeGroup:
    """A set of memories that should be merged into one."""
    kind: str
    memories: list[Memory]


@dataclass(frozen=True)
class MergeResult:
    """The output of a merge."""
    content: str
    confidence: float
    importance: int
    reason: str

    def is_valid(self) -> bool:
        return bool(self.content.strip())


class MemoryConsolidator:
    def __init__(
        self,
        *,
        provider: AIProvider,
        prompts: PromptManager,
        repo: MemoryRepository,
        similarity_threshold: float = 0.85,
        keyword_threshold: float = 0.6,
        min_group_size: int = 2,
        max_group_size: int = 8,
    ) -> None:
        self._provider = provider
        self._prompts = prompts
        self._repo = repo
        self._similarity_threshold = float(similarity_threshold)
        self._keyword_threshold = float(keyword_threshold)
        self._min_group_size = int(min_group_size)
        self._max_group_size = int(max_group_size)
        try:
            self._system = self._prompts.get("memory/consolidator").text
        except Exception:
            log.warning("consolidator prompt missing, using fallback")
            self._system = _FALLBACK_SYSTEM

    # ------------------------------------------------------------------
    # Grouping (pure)
    # ------------------------------------------------------------------
    def find_merge_groups(
        self,
        memories: list[Memory],
    ) -> list[MergeGroup]:
        """
        Group memories by kind, then cluster them by similarity.

        Uses vector similarity when both have embeddings from the same
        provider; otherwise falls back to keyword overlap.
        """
        groups: list[MergeGroup] = []

        by_kind: dict[str, list[Memory]] = {}
        for m in memories:
            if m.is_archived() or m.is_expired():
                continue
            by_kind.setdefault(m.kind, []).append(m)

        for kind, mems in by_kind.items():
            if len(mems) < self._min_group_size:
                continue
            clusters = self._cluster(mems)
            for cluster in clusters:
                if len(cluster) >= self._min_group_size:
                    groups.append(
                        MergeGroup(kind=kind, memories=cluster[: self._max_group_size])
                    )

        return groups

    def _cluster(self, memories: list[Memory]) -> list[list[Memory]]:
        clusters: list[list[Memory]] = []
        used: set[str] = set()

        for i, a in enumerate(memories):
            if a.memory_id in used:
                continue
            group = [a]
            used.add(a.memory_id)
            for b in memories[i + 1:]:
                if b.memory_id in used:
                    continue
                if self._are_similar(a, b):
                    group.append(b)
                    used.add(b.memory_id)
            if len(group) >= self._min_group_size:
                clusters.append(group)

        return clusters

    def _are_similar(self, a: Memory, b: Memory) -> bool:
        va = a.vector()
        vb = b.vector()
        if (
            va is not None
            and vb is not None
            and a.embedding_provider
            and a.embedding_provider == b.embedding_provider
        ):
            try:
                from memory.embeddings import cosine_similarity
                sim = cosine_similarity(va, vb)
                if sim >= self._similarity_threshold:
                    return True
                if sim < 0.6:
                    return False
            except Exception:
                pass

        ta = set(_tokenize(a.content))
        tb = set(_tokenize(b.content))
        if not ta or not tb:
            return False
        inter = ta & tb
        union = ta | tb
        jaccard = len(inter) / float(len(union)) if union else 0.0
        return jaccard >= self._keyword_threshold

    # ------------------------------------------------------------------
    # Merging (LLM)
    # ------------------------------------------------------------------
    def merge_group(self, group: MergeGroup, *, model: str) -> Optional[MergeResult]:
        if len(group.memories) < self._min_group_size:
            return None

        payload = {
            "kind": group.kind,
            "memories": [m.content for m in group.memories],
        }

        request = ChatRequest(
            model=model,
            messages=(
                ChatMessage(role=Role.SYSTEM, content=self._system),
                ChatMessage(
                    role=Role.USER,
                    content=json.dumps(payload, ensure_ascii=False, indent=2),
                ),
            ),
            temperature=0.2,
        )

        try:
            raw = self._provider.generate_structured(request, _SCHEMA)
        except ProviderError as exc:
            log.warning("consolidator: provider error: %s", exc)
            return None
        except Exception:
            log.exception("consolidator: unexpected error")
            return None

        errors = validate(_SCHEMA, raw)
        if errors:
            log.warning("consolidator: schema invalid: %s", "; ".join(errors[:3]))
            return None

        try:
            content = str(raw.get("content", "")).strip()
            confidence = float(raw.get("confidence", 0.85))
            importance = int(raw.get("importance", 3))
            reason = str(raw.get("reason", "")).strip()
        except (TypeError, ValueError):
            return None

        if not content:
            return None

        return MergeResult(
            content=content,
            confidence=max(0.0, min(1.0, confidence)),
            importance=max(1, min(5, importance)),
            reason=reason or "consolidated",
        )


_FALLBACK_SYSTEM = (
    "You merge several similar memories into one canonical memory. "
    "Preserve every fact, prefer the most specific wording, "
    "output JSON: {\"content\": str, \"confidence\": float, "
    "\"importance\": int, \"reason\": str}."
)