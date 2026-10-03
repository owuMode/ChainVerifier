# gui/web/memory_extract_worker.py
"""
MemoryExtractWorker — run memory extraction off the UI thread.

Design:
  * Novelty check runs FIRST (local, 0 API calls). If the conversation
    has nothing new compared to existing memories, we skip the LLM
    extractor entirely.
  * On extraction, candidates are deduped and stored in a batch.
  * Never raises.
"""

from __future__ import annotations

import traceback
from typing import Optional

from PySide6.QtCore import QThread, Signal

from applog.logger import get_logger
from memory.novelty import tokenize

log = get_logger("gui.web.memory_extract_worker")


# Minimum new tokens required to bother with an LLM extraction.
MIN_NEW_TOKENS = 3


class MemoryExtractWorker(QThread):
    extracted = Signal(int)

    def __init__(
        self,
        *,
        extractor,
        memory_manager,
        messages_repo,
        conversation_id: str,
        model: str,
        parent: Optional[QThread] = None,
    ) -> None:
        super().__init__(parent)
        self._extractor = extractor
        self._memory = memory_manager
        self._messages = messages_repo
        self._conversation_id = conversation_id
        self._model = model

    # ------------------------------------------------------------------
    def run(self) -> None:
        try:
            self._run_inner()
        except Exception:
            log.error(
                "memory extract: worker crashed\n" + traceback.format_exc()
            )

    def _run_inner(self) -> None:
        log.info("memory extract: worker started")

        if self._extractor is None:
            log.info("memory extract: skipped (no extractor)")
            return
        if self._memory is None:
            log.info("memory extract: skipped (no memory manager)")
            return
        if self._messages is None:
            log.info("memory extract: skipped (no messages repo)")
            return
        if not self._conversation_id:
            log.info("memory extract: skipped (no conversation id)")
            return

        # 1. Load messages
        try:
            rows = self._messages.latest(self._conversation_id, limit=20)
        except Exception:
            log.exception("memory extract: could not load messages")
            return

        messages = [
            {"role": m.role, "content": m.content}
            for m in rows
            if m.role in ("user", "assistant") and m.content
        ]
        log.info("memory extract: loaded messages", extra={"count": len(messages)})

        if len(messages) < 2:
            log.info("memory extract: too few messages, skipping")
            return

        # 2. Novelty check (LOCAL, no API call)
        if not self._has_novel_content(messages):
            log.info("memory extract: skipped (no new content)")
            return

        # 3. Call the LLM extractor
        log.info("memory extract: calling extractor", extra={"model": self._model})
        try:
            candidates = self._extractor.extract(messages=messages, model=self._model)
        except Exception:
            log.exception("memory extract: extractor raised")
            return

        log.info("memory extract: extractor returned", extra={"count": len(candidates)})

        if not candidates:
            return

        # 4. Store
        try:
            stored = self._memory.remember_extracted(
                candidates,
                source_conversation_id=self._conversation_id,
            )
        except Exception:
            log.exception("memory extract: store failed")
            return

        log.info("memory extract: stored", extra={"count": len(stored)})

        if stored:
            try:
                self.extracted.emit(len(stored))
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _has_novel_content(self, messages: list[dict]) -> bool:
        """
        True if the conversation contains enough new tokens that
        aren't already in stored memories.
        """
        try:
            known = self._known_tokens()
        except Exception:
            log.exception("memory extract: could not gather known tokens")
            return True  # fail open — safer to run extraction

        conv_tokens: set[str] = set()
        for m in messages:
            conv_tokens |= tokenize(m.get("content", ""))

        new_tokens = conv_tokens - known
        log.info(
            "memory extract: novelty check",
            extra={
                "conv_tokens": len(conv_tokens),
                "known_tokens": len(known),
                "new_tokens": len(new_tokens),
                "threshold": MIN_NEW_TOKENS,
            },
        )
        return len(new_tokens) >= MIN_NEW_TOKENS

    def _known_tokens(self) -> set[str]:
        """
        Collect tokens from every non-archived memory. Capped to keep
        this fast.
        """
        known: set[str] = set()
        try:
            mems = self._memory.list_all(limit=500)
        except Exception:
            return known
        for m in mems:
            try:
                known |= tokenize(m.content)
            except Exception:
                continue
        return known