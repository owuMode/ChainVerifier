# core/services/conversation_context.py
"""
ConversationContext — remember the previous chat.

When a new conversation starts, this service summarizes the previous
conversation (if it had enough content) and returns a short block
that can be injected into the new chat's system prompt.

Design:
  * Summary is generated once per conversation, then cached in
    conversations.metadata.
  * Never raises. On any failure, returns "".
  * Only summarizes conversations with >= MIN_MESSAGES messages.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from applog.logger import get_logger
from prompts.manager import PromptManager
from providers.base.models import ChatMessage, ChatRequest, Role
from providers.base.provider import AIProvider, ProviderError

log = get_logger("core.services.conversation_context")


MIN_MESSAGES = 4
MAX_CHARS_SUMMARY = 800


@dataclass(frozen=True)
class RecentSummary:
    conversation_id: str
    text: str
    generated_at: str


class ConversationContext:
    def __init__(
        self,
        *,
        provider: AIProvider,
        prompts: PromptManager,
        model: str,
        conversations_repo,
        messages_repo,
    ) -> None:
        self._provider = provider
        self._prompts = prompts
        self._model = model
        self._conversations = conversations_repo
        self._messages = messages_repo

    # ------------------------------------------------------------------
    def summary_for_previous_conversation(
        self,
        *,
        current_conversation_id: str,
    ) -> str:
        """
        Return a short block summarizing the most recent conversation
        that is NOT the current one. Returns "" if there is nothing
        useful to say.
        """
        try:
            recent = self._conversations.list_recent(limit=5)
        except Exception:
            log.exception("could not list conversations")
            return ""

        previous = None
        for c in recent:
            if c.conversation_id == current_conversation_id:
                continue
            previous = c
            break

        if previous is None:
            return ""

        # Already cached?
        cached = _extract_summary_from_metadata(previous.metadata)
        if cached:
            return _format_block(cached, previous.title)

        # Count messages
        try:
            msgs = self._messages.list_for_conversation(previous.conversation_id)
        except Exception:
            log.exception("could not load messages for summary")
            return ""

        if len(msgs) < MIN_MESSAGES:
            return ""

        # Generate
        text = self._generate_summary(previous.conversation_id, msgs)
        if not text:
            return ""

        # Cache in metadata
        self._store_summary_in_metadata(previous.conversation_id, text)

        return _format_block(text, previous.title)

    # ------------------------------------------------------------------
    def _generate_summary(self, conversation_id: str, msgs: list) -> str:
        # Only user + assistant messages, capped.
        trimmed = [
            {"role": m.role, "content": m.content[:400]}
            for m in msgs
            if m.role in ("user", "assistant") and m.content
        ][-20:]

        if not trimmed:
            return ""

        payload = json.dumps({"messages": trimmed}, ensure_ascii=False, indent=2)

        system = (
            "You summarize a previous conversation in one or two short "
            "sentences. Focus on: the user's goals, decisions, and any "
            "ongoing projects. Do NOT include greetings. Match the "
            "user's language. Return plain text, no JSON."
        )

        request = ChatRequest(
            model=self._model,
            messages=(
                ChatMessage(role=Role.SYSTEM, content=system),
                ChatMessage(role=Role.USER, content=payload),
            ),
            temperature=0.2,
        )

        try:
            resp = self._provider.chat(request)
        except ProviderError as exc:
            log.info("summary: provider error: %s", exc)
            return ""
        except Exception:
            log.exception("summary: unexpected error")
            return ""

        text = (resp.content or "").strip()
        if not text:
            return ""
        if len(text) > MAX_CHARS_SUMMARY:
            text = text[: MAX_CHARS_SUMMARY - 1].rstrip() + "…"
        return text

    # ------------------------------------------------------------------
    def _store_summary_in_metadata(self, conversation_id: str, text: str) -> None:
        try:
            conv = self._conversations.get(conversation_id)
            if conv is None:
                return
            meta = dict(conv.metadata or {})
            meta["summary"] = text
            from datetime import datetime, timezone
            meta["summary_generated_at"] = datetime.now(timezone.utc).isoformat()

            # Persist via raw SQL (the repo has no generic metadata setter).
            with self._conversations._db.transaction() as conn:
                conn.execute(
                    "UPDATE conversations SET metadata = ? WHERE conversation_id = ?;",
                    (json.dumps(meta, ensure_ascii=False), conversation_id),
                )
            log.info(
                "summary cached",
                extra={"conversation_id": conversation_id, "chars": len(text)},
            )
        except Exception:
            log.exception("failed to cache summary")


# ----------------------------------------------------------------------
def _extract_summary_from_metadata(metadata: dict) -> Optional[str]:
    if not isinstance(metadata, dict):
        return None
    text = metadata.get("summary")
    if not text:
        return None
    return str(text).strip() or None


def _format_block(summary_text: str, previous_title: str = "") -> str:
    if not summary_text:
        return ""
    header = "## What we talked about recently"
    if previous_title:
        header += f" (\"{previous_title}\")"
    return f"{header}\n{summary_text}"