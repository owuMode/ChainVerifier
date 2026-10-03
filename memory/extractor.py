# memory/extractor.py
"""
MemoryExtractor — LLM-driven extraction of long-term memories.

Given a conversation (user + assistant messages), ask the model to
return a small JSON array of durable facts about the user.

Design:
  * Never raises. Returns an empty list on any failure.
  * Filters candidates through the memory policy before returning.
  * The caller (MemoryManager) is responsible for storing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from applog.logger import get_logger
from memory.policies import DEFAULT_LIMITS, MemoryLimits, is_worth_storing
from memory.repositories import ALLOWED_KINDS
from prompts.manager import PromptManager
from providers.base.models import ChatMessage, ChatRequest, Role
from providers.base.provider import AIProvider, ProviderError
from security.validation import validate

log = get_logger("memory.extractor")


_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "memories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "content": {"type": "string", "minLength": 4, "maxLength": 2000},
                    "importance": {"type": "integer", "minimum": 1, "maximum": 5},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["kind", "content"],
            },
        },
    },
    "required": ["memories"],
}


@dataclass(frozen=True)
class ExtractedMemory:
    kind: str
    content: str
    importance: int
    confidence: float
    tags: tuple[str, ...]


class MemoryExtractor:
    def __init__(
        self,
        provider: AIProvider,
        prompts: PromptManager,
        *,
        limits: MemoryLimits = DEFAULT_LIMITS,
    ) -> None:
        self._provider = provider
        self._prompts = prompts
        self._limits = limits
        try:
            self._system = self._prompts.get("memory/extractor").text
        except Exception:
            log.warning("memory extractor prompt missing, using fallback")
            self._system = _FALLBACK_SYSTEM

    # ------------------------------------------------------------------
    def extract(
        self,
        *,
        messages: list[dict],
        model: str,
        max_candidates: Optional[int] = None,
    ) -> list[ExtractedMemory]:
        """
        Extract memories from a list of {role, content} messages.

        Never raises. Returns [] on any failure.
        """
        if not messages:
            return []

        cap = max_candidates or self._limits.max_extracted_per_turn
        user_prompt = _build_user_prompt(messages)

        request = ChatRequest(
            model=model,
            messages=(
                ChatMessage(role=Role.SYSTEM, content=self._system),
                ChatMessage(role=Role.USER, content=user_prompt),
            ),
            temperature=0.0,
        )

        try:
            raw = self._provider.generate_structured(request, _SCHEMA)
        except ProviderError as exc:
            log.warning("extractor: provider error: %s", exc)
            return []
        except Exception:
            log.exception("extractor: unexpected error")
            return []

        errors = validate(_SCHEMA, raw)
        if errors:
            log.warning("extractor: schema invalid: %s", "; ".join(errors[:3]))
            return []

        out: list[ExtractedMemory] = []
        for item in (raw.get("memories") or [])[:cap]:
            kind = str(item.get("kind", "")).strip().lower()
            content = str(item.get("content", "")).strip()
            if kind not in ALLOWED_KINDS:
                kind = "other"
            if not content:
                continue
            try:
                importance = int(item.get("importance", 3))
            except (TypeError, ValueError):
                importance = 3
            try:
                confidence = float(item.get("confidence", 0.75))
            except (TypeError, ValueError):
                confidence = 0.75
            tags_raw = item.get("tags") or []
            tags = tuple(str(t).strip().lower() for t in tags_raw if isinstance(t, str))[:10]

            if not is_worth_storing(
                content=content, confidence=confidence, limits=self._limits
            ):
                log.info(
                    "extractor: rejected by policy",
                    extra={"kind": kind, "len": len(content), "confidence": confidence},
                )
                continue

            out.append(
                ExtractedMemory(
                    kind=kind,
                    content=content,
                    importance=max(1, min(5, importance)),
                    confidence=max(0.0, min(1.0, confidence)),
                    tags=tags,
                )
            )

        log.info("extractor: %d candidate(s) extracted", len(out))
        return out


_FALLBACK_SYSTEM = (
    "You extract durable facts about the user from a conversation. "
    "Return JSON: {\"memories\": [{\"kind\": str, \"content\": str, "
    "\"importance\": int, \"confidence\": float, \"tags\": [str]}]}. "
    "Skip passwords, keys, and one-time requests."
)


def _build_user_prompt(messages: list[dict]) -> str:
    lines: list[str] = ["Conversation:"]
    for m in messages:
        role = str(m.get("role", "")).strip().lower()
        content = str(m.get("content", "")).strip()
        if not content:
            continue
        if role not in ("user", "assistant"):
            continue
        lines.append(f"{role.upper()}: {content}")
    lines.append("")
    lines.append("Return memories as JSON.")
    return "\n".join(lines)