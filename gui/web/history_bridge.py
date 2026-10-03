# gui/web/history_bridge.py
"""
HistoryBridge — Python <-> JS boundary for chat persistence.

Phase 3: conversation export to Markdown.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from applog.logger import get_logger

log = get_logger("gui.web.history_bridge")


_ROLE_ALIASES = {
    "ai": "assistant",
    "bot": "assistant",
    "human": "user",
}


class HistoryBridge(QObject):
    conversationsChanged = Signal()

    def __init__(
        self,
        *,
        conversations_repo,
        messages_repo,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._conversations = conversations_repo
        self._messages = messages_repo

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------
    @Slot(result=str)
    def listConversationsJson(self) -> str:
        try:
            conversations = self._conversations.list_recent(limit=50)
        except Exception:
            log.exception("listConversationsJson failed")
            return "[]"
        payload = [
            {
                "id": c.conversation_id,
                "title": c.title,
                "updated_at": c.updated_at,
            }
            for c in conversations
        ]
        return json.dumps(payload, ensure_ascii=False)

    @Slot(str, str, result=str)
    def ensureConversation(self, conversation_id: str, title: str) -> str:
        if not conversation_id:
            return ""
        try:
            if self._conversations.exists(conversation_id):
                return conversation_id
            conv = self._conversations.create(
                title=title or "",
                conversation_id=conversation_id,
            )
            self.conversationsChanged.emit()
            return conv.conversation_id
        except Exception:
            log.exception(
                "ensureConversation failed",
                extra={"conversation_id": conversation_id},
            )
            return ""

    @Slot(str, str)
    def renameConversation(self, conversation_id: str, title: str) -> None:
        try:
            self._conversations.rename(conversation_id, title or "")
            self.conversationsChanged.emit()
        except Exception:
            log.exception(
                "renameConversation failed",
                extra={"conversation_id": conversation_id},
            )

    @Slot(str)
    def deleteConversation(self, conversation_id: str) -> None:
        try:
            self._conversations.delete(conversation_id)
            self.conversationsChanged.emit()
        except Exception:
            log.exception(
                "deleteConversation failed",
                extra={"conversation_id": conversation_id},
            )

    @Slot(result=int)
    def deleteAllConversations(self) -> int:
        try:
            deleted = self._conversations.delete_all()
            self.conversationsChanged.emit()
            return int(deleted)
        except Exception:
            log.exception("deleteAllConversations failed")
            return 0

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------
    @Slot(str, result=str)
    def listMessagesJson(self, conversation_id: str) -> str:
        try:
            messages = self._messages.list_for_conversation(conversation_id)
        except Exception:
            log.exception(
                "listMessagesJson failed",
                extra={"conversation_id": conversation_id},
            )
            return "[]"
        payload = [
            {
                "id": m.message_id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at,
            }
            for m in messages
        ]
        return json.dumps(payload, ensure_ascii=False)

    @Slot(str, str, str, result=str)
    def appendMessage(
        self,
        conversation_id: str,
        role: str,
        content: str,
    ) -> str:
        db_role = _ROLE_ALIASES.get(str(role).strip().lower(), role)
        try:
            msg = self._messages.append(conversation_id, db_role, content)
            self._conversations.touch(conversation_id)
            return msg.message_id
        except Exception:
            log.exception(
                "appendMessage failed",
                extra={"conversation_id": conversation_id, "role": db_role},
            )
            return ""

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    @Slot(str, result=str)
    def exportConversationJson(self, conversation_id: str) -> str:
        """
        Return JSON: {"ok": bool, "filename": str, "path": str, "markdown": str}
        """
        try:
            conv = self._conversations.get(conversation_id)
        except Exception:
            log.exception("export: conversation lookup failed")
            return json.dumps({"ok": False, "reason": "lookup failed"})
        if conv is None:
            return json.dumps({"ok": False, "reason": "not found"})

        try:
            messages = self._messages.list_for_conversation(conversation_id)
        except Exception:
            log.exception("export: message lookup failed")
            return json.dumps({"ok": False, "reason": "messages unavailable"})

        # Build markdown.
        title = conv.title or "Untitled chat"
        created = conv.created_at or ""
        lines: list[str] = []
        lines.append(f"# {title}")
        lines.append("")
        lines.append(f"*Exported: {_utc_now_human()}*")
        if created:
            lines.append(f"*Created: {created}*")
        lines.append("")
        lines.append("---")
        lines.append("")

        for m in messages:
            role = str(m.role or "").lower()
            if role == "user":
                heading = "## You"
            elif role == "assistant":
                heading = "## Rhea"
            elif role == "system":
                heading = "## System"
            elif role == "tool":
                heading = "## Tool"
            else:
                heading = f"## {role.title()}"

            lines.append(heading)
            lines.append("")
            content = (m.content or "").rstrip()
            if content:
                lines.append(content)
            else:
                lines.append("*(empty)*")
            lines.append("")

        markdown = "\n".join(lines).strip() + "\n"

        # Safe filename.
        safe = _safe_filename(title)
        filename = f"{safe}.md"

        # Write into user's Downloads folder.
        try:
            from pathlib import Path
            downloads = Path.home() / "Downloads"
            downloads.mkdir(parents=True, exist_ok=True)
            target = downloads / filename
            target.write_text(markdown, encoding="utf-8")
            path = str(target)
        except Exception:
            log.exception("export: write failed")
            return json.dumps({
                "ok": False,
                "reason": "write failed",
                "markdown": markdown,
            })

        log.info("conversation exported", extra={"path": path})
        return json.dumps({
            "ok": True,
            "filename": filename,
            "path": path,
            "markdown": markdown,
        }, ensure_ascii=False)


def _utc_now_human() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _safe_filename(name: str) -> str:
    bad = '\\/:*?"<>|'
    out_chars: list[str] = []
    for ch in (name or "chat"):
        out_chars.append("_" if ch in bad else ch)
    safe = "".join(out_chars).strip().strip(".")
    if not safe:
        safe = "chat"
    if len(safe) > 80:
        safe = safe[:80].rstrip()
    return safe