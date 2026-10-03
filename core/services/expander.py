
# core/services/expander.py
"""
ShortMessageExpander — turn a very short message into a full request
using recent conversation context.

Design:
  * Only runs on messages under MAX_WORDS words.
  * Skips if the message already contains a task verb AND a target.
  * Never raises. On any failure, returns the original message.
  * Cached per conversation: identical short message + same context
    reuses the previous expansion.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Optional

from applog.logger import get_logger
from prompts.manager import PromptManager
from providers.base.models import ChatMessage, ChatRequest, Role
from providers.base.provider import AIProvider, ProviderError
from security.validation import validate

log = get_logger("core.services.expander")


MAX_WORDS = 5

_SCHEMA = {
    "type": "object",
    "properties": {
        "expanded": {"type": "string", "minLength": 1, "maxLength": 1000},
        "changed": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": ["expanded"],
}


_TASK_VERB_RE = re.compile(
    r"\b(open|launch|start|run|list|read|write|create|delete|remove|move|"
    r"rename|find|search|close|kill|kholo|khol|chalao|chalado|banao|bana|"
    r"dhundo|dhoondo|likho|likh|padho|padh|dikhao|dikha|band|bandh)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExpansionResult:
    expanded: str
    changed: bool
    confidence: float


class ShortMessageExpander:
    def __init__(
        self,
        *,
        provider: AIProvider,
        prompts: PromptManager,
        model: str,
        cache=None,
    ) -> None:
        self._provider = provider
        self._prompts = prompts
        self._model = model
        self._cache = cache
        try:
            self._system = self._prompts.get("chat/expander").text
        except Exception:
            log.warning("expander prompt missing, using fallback")
            self._system = _FALLBACK_SYSTEM

    # ------------------------------------------------------------------
    def expand(
        self,
        *,
        user_message: str,
        recent_messages: list[dict],
    ) -> ExpansionResult:
        text = (user_message or "").strip()
        if not text:
            return ExpansionResult(expanded=text, changed=False, confidence=0.0)

        # Not short? Return unchanged.
        if len(text.split()) > MAX_WORDS:
            return ExpansionResult(expanded=text, changed=False, confidence=0.0)

        # Contains both a task verb AND a target noun -> no need to expand.
        if _TASK_VERB_RE.search(text) and len(text.split()) >= 2:
            return ExpansionResult(expanded=text, changed=False, confidence=0.9)

        # No context to expand from.
        if not recent_messages:
            return ExpansionResult(expanded=text, changed=False, confidence=0.0)

        # Cache lookup
        cached = self._cache_get(text, recent_messages)
        if cached is not None:
            return cached

        # Build request
        payload = {
            "recent_messages": recent_messages[-6:],
            "user_message": text,
        }
        request = ChatRequest(
            model=self._model,
            messages=(
                ChatMessage(role=Role.SYSTEM, content=self._system),
                ChatMessage(
                    role=Role.USER,
                    content=json.dumps(payload, ensure_ascii=False, indent=2),
                ),
            ),
            temperature=0.0,
        )

        try:
            raw = self._provider.generate_structured(request, _SCHEMA)
        except ProviderError as exc:
            log.info("expander: provider error: %s", exc)
            return ExpansionResult(expanded=text, changed=False, confidence=0.0)
        except Exception:
            log.exception("expander: unexpected error")
            return ExpansionResult(expanded=text, changed=False, confidence=0.0)

        errors = validate(_SCHEMA, raw)
        if errors:
            log.info("expander: schema invalid: %s", "; ".join(errors[:3]))
            return ExpansionResult(expanded=text, changed=False, confidence=0.0)

        try:
            expanded = str(raw.get("expanded", "")).strip()
            changed = bool(raw.get("changed", False))
            confidence = float(raw.get("confidence", 0.0))
        except (TypeError, ValueError):
            return ExpansionResult(expanded=text, changed=False, confidence=0.0)

        if not expanded:
            return ExpansionResult(expanded=text, changed=False, confidence=0.0)

        result = ExpansionResult(
            expanded=expanded,
            changed=changed,
            confidence=max(0.0, min(1.0, confidence)),
        )

        self._cache_put(text, recent_messages, result)
        log.info(
            "expander: expanded",
            extra={
                "from_len": len(text),
                "to_len": len(expanded),
                "changed": changed,
            },
        )
        return result

    # ------------------------------------------------------------------
    def _cache_key(self, text: str, recent_messages: list[dict]) -> str:
        tail = "|".join(
            f"{m.get('role','')}:{str(m.get('content',''))[:80]}"
            for m in recent_messages[-3:]
        )
        blob = f"{text}||{tail}".encode("utf-8", errors="replace")
        return hashlib.sha256(blob).hexdigest()

    def _cache_get(
        self,
        text: str,
        recent_messages: list[dict],
    ) -> Optional[ExpansionResult]:
        if self._cache is None:
            return None
        try:
            key = self._cache_key(text, recent_messages)
            hit = self._cache.get(key)
        except Exception:
            return None
        if hit is None:
            return None
        return ExpansionResult(
            expanded=hit.get("expanded", text),
            changed=bool(hit.get("changed", False)),
            confidence=float(hit.get("confidence", 0.0)),
        )

    def _cache_put(
        self,
        text: str,
        recent_messages: list[dict],
        result: ExpansionResult,
    ) -> None:
        if self._cache is None:
            return
        try:
            key = self._cache_key(text, recent_messages)
            self._cache.put(
                key,
                {
                    "expanded": result.expanded,
                    "changed": result.changed,
                    "confidence": result.confidence,
                },
            )
        except Exception:
            pass


_FALLBACK_SYSTEM = (
    "You expand a very short user message into a full request using "
    "the recent conversation. Return JSON: "
    "{\"expanded\": str, \"changed\": bool, \"confidence\": float}. "
    "Never answer the request — only rephrase it."
)