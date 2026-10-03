# core/services/chat_service.py
"""
ChatService — direct conversation with the AI, no tools, no planning.

Phase 3 additions:
  * handle_memory_command() — process a memory command.
    For "list" we return a deterministic formatted reply (no LLM
    call — LLMs add latency and cost for what is pure formatting).
    For other actions we ask the LLM for a natural reply.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterator, Optional

from applog.logger import get_logger
from prompts.manager import PromptManager
from providers.base.models import (
    ChatMessage,
    ChatRequest,
    Role,
    StreamChunk,
)
from providers.base.provider import AIProvider, ProviderError

log = get_logger("core.services.chat")


_FALLBACK_SYSTEM = (
    "You are Rhea, a helpful conversational AI assistant on the "
    "user's Windows PC. Match the user's language. Answer directly. "
    "Never claim to be a planner or 'reasoning component'."
)


_MEMORY_REPLY_SYSTEM = """You are Rhea, a helpful AI assistant.
The user just issued a memory command. The system has already
executed it. Your job is to write a short, natural reply describing
what happened.

Rules:
- Match the user's language exactly (English, Hindi, Hinglish, etc.).
- Be warm, natural, human. 1-2 sentences max.
- Do NOT mention tools, internals, APIs, databases, memory systems,
  or "the system".
- If you just stored info, acknowledge it warmly and mention what
  you stored.
- If you just forgot info, gently confirm.
- If you updated info, confirm the new value.
- Do NOT invent memories or actions that did not happen.

Output ONLY the reply text — no JSON, no quotes, no prefix.
"""


@dataclass
class ChatReply:
    text: str
    error: Optional[str] = None


@dataclass
class ChatStreamChunk:
    delta_text: str = ""
    done: bool = False
    error: Optional[str] = None


class ChatService:
    def __init__(
        self,
        provider: AIProvider,
        prompts: PromptManager,
        model: str,
        *,
        memory_manager=None,
        conversation_context=None,
        expander=None,
        config=None,
    ) -> None:
        self._provider = provider
        self._prompts = prompts
        self._model = model
        self._memory = memory_manager
        self._context = conversation_context
        self._expander = expander
        self._config = config
        self._base_system = self._load_chat_prompt()

    # ------------------------------------------------------------------
    def reply(
        self,
        user_message: str,
        history: tuple[ChatMessage, ...] = (),
        *,
        conversation_id: Optional[str] = None,
        memory_enabled: bool = True,
    ) -> ChatReply:
        messages = self._build_messages(
            user_message, history,
            conversation_id=conversation_id,
            memory_enabled=memory_enabled,
        )

        request = ChatRequest(
            model=self._model,
            messages=messages,
            temperature=0.7,
        )

        try:
            response = self._provider.chat(request)
        except ProviderError as exc:
            log.warning("chat: provider error: %s", exc)
            return ChatReply(
                text=_humanize_provider_error(str(exc)),
                error=str(exc),
            )
        except Exception as exc:
            log.exception("chat: unexpected error")
            return ChatReply(
                text=f"Something went wrong: {type(exc).__name__}",
                error=str(exc),
            )

        text = (response.content or "").strip()
        if not text:
            text = "(empty response from model)"
        return ChatReply(text=text)

    # ------------------------------------------------------------------
    def handle_memory_command(
        self,
        *,
        action: str,
        target: str,
        new_value: str = "",
    ) -> ChatReply:
        """
        Handle a memory_command classification.
        """
        if self._memory is None:
            return ChatReply(
                text=(
                    "Memory is currently turned off. Enable it in "
                    "Settings if you want me to remember things."
                )
            )

        action = (action or "").strip().lower()
        target = (target or "").strip()
        new_value = (new_value or "").strip()

        # ---- 1. Execute the operation --------------------------------
        result: dict = {
            "action": action,
            "target": target,
            "new_value": new_value,
            "items": [],
            "error": None,
            "count": 0,
        }

        try:
            if action == "clear":
                n = self._memory.forget_all()
                result["count"] = n
                return ChatReply(
                    text=self._deterministic_reply("clear", result)
                )

            elif action == "list":
                items = self._memory.list_all(limit=50)
                result["items"] = [
                    {"kind": m.kind, "content": m.content}
                    for m in items
                ]
                result["count"] = len(items)
                # Skip the LLM for "list" — it is pure formatting.
                return ChatReply(
                    text=self._deterministic_reply("list", result)
                )

            elif action == "forget":
                if not target:
                    return ChatReply(
                        text="Kya bhoolna hai? Batao, main hata dungi."
                    )
                archived = self._memory.forget_by_query(target)
                result["count"] = len(archived)
                result["items"] = [
                    {"kind": m.kind, "content": m.content}
                    for m in archived
                ]

            elif action == "update":
                if not new_value:
                    return ChatReply(
                        text="Naya value kya hai? Bolo, main update kar dungi."
                    )
                mem = self._memory.update_by_query(
                    query=target,
                    new_value=new_value,
                )
                result["count"] = 1 if mem else 0
                if mem is not None:
                    result["items"] = [
                        {"kind": mem.kind, "content": mem.content}
                    ]

            elif action == "remember":
                content = target or new_value
                if not content:
                    return ChatReply(
                        text="Kya yaad rakhna hai? Batao."
                    )
                mem = self._memory.remember(
                    content,
                    source="explicit",
                    confidence=0.95,
                )
                result["count"] = 1 if mem else 0
                if mem is not None:
                    result["items"] = [
                        {"kind": mem.kind, "content": mem.content}
                    ]
                else:
                    # Dedupe or policy reject — but the user asked.
                    return ChatReply(
                        text=(
                            "Ye to mujhe pehle se hi yaad hai."
                            if action == "remember"
                            else self._deterministic_reply(action, result)
                        )
                    )

            else:
                return ChatReply(text="Theek hai.")

        except Exception:
            log.exception("chat: memory command execution failed")
            return ChatReply(
                text="Kuch problem aa gayi. Phir se try karo."
            )

        # ---- 2. Natural LLM reply for remember/forget/update --------
        natural = self._generate_memory_reply(result)
        if natural:
            return ChatReply(text=natural)

        # ---- 3. Deterministic fallback -------------------------------
        return ChatReply(text=self._deterministic_reply(action, result))

    # ------------------------------------------------------------------
    def _generate_memory_reply(self, result: dict) -> str:
        """
        Ask the LLM for a natural reply. Returns "" on any failure.
        """
        try:
            payload = {
                "action": result.get("action"),
                "target": result.get("target"),
                "new_value": result.get("new_value"),
                "count": result.get("count", 0),
                "items": result.get("items", [])[:20],
            }
            user_msg = json.dumps(payload, ensure_ascii=False, indent=2)

            request = ChatRequest(
                model=self._model,
                messages=(
                    ChatMessage(role=Role.SYSTEM, content=_MEMORY_REPLY_SYSTEM),
                    ChatMessage(role=Role.USER, content=user_msg),
                ),
                temperature=0.5,
            )

            response = self._provider.chat(request)
            text = (response.content or "").strip()
            if not text:
                return ""
            return text.strip('"').strip("'").strip()
        except Exception:
            log.exception("chat: natural memory reply failed")
            return ""

    # ------------------------------------------------------------------
    def _deterministic_reply(self, action: str, result: dict) -> str:
        """
        Small, natural reply — no LLM. Used for list/clear, and as a
        fallback when the LLM path fails.
        """
        count = int(result.get("count", 0))
        items = result.get("items", [])

        if action == "remember":
            return "Theek hai, yaad rakh liya."
        if action == "forget":
            if count == 0:
                return "Mere paas is baare me kuch yaad nahi tha."
            return "Theek hai, yaad se hata diya."
        if action == "update":
            return "Update kar diya."
        if action == "clear":
            return f"Theek hai, saari memories hata di ({count})."
        if action == "list":
            if not items:
                return "Abhi mere paas aapke baare me kuch yaad nahi hai."
            lines = ["Mujhe aapke baare me ye yaad hai:"]
            for it in items[:20]:
                kind = str(it.get("kind", "")).upper()
                content = str(it.get("content", "")).strip()
                lines.append(f"  • [{kind}] {content}")
            if len(items) > 20:
                lines.append(f"  … aur {len(items) - 20} more")
            return "\n".join(lines)
        return "Theek hai."

    # ------------------------------------------------------------------
    def stream_reply(
        self,
        user_message: str,
        history: tuple[ChatMessage, ...] = (),
        *,
        conversation_id: Optional[str] = None,
        memory_enabled: bool = True,
    ) -> Iterator[ChatStreamChunk]:
        messages = self._build_messages(
            user_message, history,
            conversation_id=conversation_id,
            memory_enabled=memory_enabled,
        )

        request = ChatRequest(
            model=self._model,
            messages=messages,
            temperature=0.7,
            stream=True,
        )

        try:
            stream = self._provider.stream(request)
        except ProviderError as exc:
            log.warning("chat stream: provider error: %s", exc)
            yield ChatStreamChunk(
                delta_text=_humanize_provider_error(str(exc)),
                done=True,
                error=str(exc),
            )
            return
        except Exception as exc:
            log.exception("chat stream: unexpected error")
            yield ChatStreamChunk(
                delta_text=f"Something went wrong: {type(exc).__name__}",
                done=True,
                error=str(exc),
            )
            return

        try:
            for chunk in stream:
                if chunk is None:
                    continue
                if getattr(chunk, "done", False):
                    yield ChatStreamChunk(delta_text="", done=True)
                    return
                text = getattr(chunk, "delta_text", "") or ""
                if text:
                    yield ChatStreamChunk(delta_text=text, done=False)
        except ProviderError as exc:
            log.warning("chat stream: mid-stream error: %s", exc)
            yield ChatStreamChunk(
                delta_text="",
                done=True,
                error=str(exc),
            )
            return
        except Exception as exc:
            log.exception("chat stream: mid-stream unexpected error")
            yield ChatStreamChunk(
                delta_text="",
                done=True,
                error=f"{type(exc).__name__}: {exc}",
            )
            return

        yield ChatStreamChunk(delta_text="", done=True)

    # ------------------------------------------------------------------
    def _build_messages(
        self,
        user_message: str,
        history: tuple[ChatMessage, ...],
        *,
        conversation_id: Optional[str],
        memory_enabled: bool = True,
    ) -> tuple[ChatMessage, ...]:
        system_content = self._base_system

        if self._config is not None and self._context is not None:
            try:
                continuity_on = bool(self._config.get("memory.continuity.enabled", True))
            except Exception:
                continuity_on = True
            if continuity_on and conversation_id:
                try:
                    block = self._context.summary_for_previous_conversation(
                        current_conversation_id=conversation_id,
                    )
                    if block:
                        system_content = f"{system_content}\n\n{block}"
                        log.info(
                            "chat: injected continuity block",
                            extra={"chars": len(block)},
                        )
                except Exception:
                    log.exception("chat: continuity injection failed")

        if memory_enabled and self._memory is not None:
            try:
                block = self._memory.recall_block(user_message)
                if block:
                    system_content = f"{system_content}\n\n{block}"
                    log.info(
                        "chat: injected memory block",
                        extra={"chars": len(block)},
                    )
            except Exception:
                log.exception("chat: memory injection failed")

        effective_message = user_message
        if self._config is not None and self._expander is not None:
            try:
                expander_on = bool(self._config.get("memory.expander.enabled", True))
            except Exception:
                expander_on = True
            if expander_on:
                try:
                    recent = _history_to_dicts(history)
                    result = self._expander.expand(
                        user_message=user_message,
                        recent_messages=recent,
                    )
                    if result.changed and result.confidence >= 0.5:
                        effective_message = result.expanded
                        log.info(
                            "chat: expanded short message",
                            extra={
                                "from": user_message[:60],
                                "to": effective_message[:60],
                            },
                        )
                except Exception:
                    log.exception("chat: expander failed")

        msgs = [ChatMessage(role=Role.SYSTEM, content=system_content)]
        msgs.extend(history)
        msgs.append(ChatMessage(role=Role.USER, content=effective_message))
        return tuple(msgs)

    def _load_chat_prompt(self) -> str:
        try:
            return self._prompts.get("chat/assistant").text
        except Exception:
            log.warning("chat prompt file missing, using fallback")
            return _FALLBACK_SYSTEM


def _history_to_dicts(history: tuple[ChatMessage, ...]) -> list[dict]:
    out: list[dict] = []
    for m in history[-6:]:
        try:
            role = m.role.value
            content = m.content or ""
            out.append({"role": role, "content": content})
        except Exception:
            continue
    return out


def _humanize_provider_error(msg: str) -> str:
    low = msg.lower()
    if "503" in low or "unavailable" in low:
        return "The AI provider is temporarily busy. Please try again in a moment."
    if "429" in low or "rate limit" in low:
        return "The AI provider is rate-limiting us. Wait a few seconds and try again."
    if "401" in low or "403" in low or "auth" in low:
        return "The API key was rejected. Check Settings and make sure your key is valid."
    if "404" in low or "not found" in low:
        return "The selected model is not available. Pick a different model in Settings."
    if "network" in low or "connection" in low:
        return "Network error. Check your internet connection."
    return f"Request failed: {msg}"