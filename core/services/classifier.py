# core/services/classifier.py
"""
Classifier — decides whether a user message is a chat request, a
tool task, or a memory command.

Phase 3: 3-way classification.

Heuristic: message that clearly asks for CODE, EXPLANATION, or
KNOWLEDGE (not an action on the machine) is ALWAYS chat, even if it
contains words like "list", "create", or "code".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from applog.logger import get_logger
from providers.base.models import ChatMessage, ChatRequest, Role
from providers.base.provider import AIProvider, ProviderError
from security.validation import validate
from tools.registry.registry import ToolRegistry

log = get_logger("core.services.classifier")


_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": ["chat", "task", "memory_command"],
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reason": {"type": "string"},
        "memory_action": {
            "type": "string",
            "enum": ["remember", "forget", "update", "list", "clear"],
        },
        "memory_target": {"type": "string"},
        "memory_new_value": {"type": "string"},
    },
    "required": ["kind"],
}


_SYSTEM = """You classify a single user message into one of three kinds:

  * "chat"             — the user is talking to the assistant: greetings,
                         questions, explanations, opinions, small talk,
                         requests for code samples, code explanations,
                         how-to guidance, or anything the assistant can
                         answer directly without touching the computer.

                         IMPORTANT: asking for a CODE EXAMPLE, a code
                         snippet, or "how to do X in language Y" is
                         ALWAYS chat. It does NOT need a tool.

  * "task"             — the user is asking the assistant to perform an
                         action on THEIR COMPUTER (open apps, control
                         windows, run commands, read/write files, list
                         folders, take screenshots, etc.).

                         Signals for task:
                           - a file, folder, or path (Desktop, Documents,
                             ~/Downloads, C:\\...)
                           - an app name (Notepad, Chrome, VSCode, Spotify)
                           - an OS action (list my Desktop, delete file
                             X, move file Y, take a screenshot)
                           - "on my computer", "on my PC", "on my Desktop"

  * "memory_command"   — the user is asking to REMEMBER, FORGET, UPDATE,
                         LIST, or CLEAR something about THEMSELVES.

Examples:

  "Give me a Python code example for a calculator with a list of features"
    → chat (asking for code, not asking to run anything)

  "how to write a binary search in C++"
    → chat

  "explain recursion with an example"
    → chat

  "list the files on my Desktop"
    → task (list files = action on computer)

  "create a file notes.txt on Desktop"
    → task

  "delete test.txt from Downloads"
    → task

  "remember my name is Siyak"
    → memory_command

IMPORTANT DISAMBIGUATION:
  - The words "list", "create", "write", "read" only indicate a task
    if they refer to something ON THE COMPUTER (files, apps, paths).
  - If the user is asking for KNOWLEDGE, CODE, or AN EXPLANATION,
    it is chat even if it contains those words.
  - "list of features" = chat.
  - "list my Desktop" = task.
  - "write a function that sorts" = chat.
  - "write a file called x.txt" = task.

For memory_command, also provide:

  memory_action: one of
      "remember" | "forget" | "update" | "list" | "clear"
  memory_target:   short phrase describing WHAT to affect
                    e.g. "my name", "coffee", "favourite colour"
  memory_new_value: only for "update" — the new value

Output ONLY a JSON object matching the schema. No prose. No markdown fences.
"""


_GREETING_RE = re.compile(
    r"^\s*(hi|hello|hey|yo|salaam|namaste|hola|good\s+(morning|evening|afternoon|night)|thanks?|thank\s+you|dhanyavaad|shukriya|ok|okay|k|hmm|haan|nahi|bye|goodbye)\b[\s\.\!\?]*$",
    re.IGNORECASE,
)

_SHORT_QUESTION_RE = re.compile(
    r"^\s*(what|who|where|when|why|how|which|kya|kaun|kahan|kab|kyun|kaise|kaisa)\b",
    re.IGNORECASE,
)

# Words that STRONGLY signal an "explain / how-to / code request".
_CHAT_INTENT_RE = re.compile(
    r"\b("
    r"code|snippet|example|sample|program|function|script|"
    r"explain|explanation|describe|teach|tutorial|"
    r"how\s+to|how\s+do\s+i|how\s+can\s+i|"
    r"what\s+is|what\s+are|why\s+does|why\s+is|"
    r"difference\s+between|compare|"
    r"algorithm|library|framework|api|syntax|"
    r"write\s+a\s+(function|program|script|class|method|algorithm)|"
    r"give\s+me\s+(an?\s+)?(example|sample|code|program|script)|"
    r"list\s+of\s+\w+|"
    r"mujhe\s+\w+\s+me\s+\w+\s+(ka\s+)?code\s+(do|de|batao)|"
    r"code\s+(do|de|batao|dikhao)"
    r")\b",
    re.IGNORECASE,
)

# User attribute signals (for memory_command).
_USER_ATTR_RE = re.compile(
    r"\b("
    r"mera\s+naam|meri\s+identity|mera\s+name|my\s+name|"
    r"mera\s+colour|meri\s+pasand|my\s+colour|my\s+favourite|"
    r"meri\s+preference|my\s+preference|"
    r"mere\s+baare\s+me|mere\s+bare\s+me|about\s+me|"
    r"mera\s+goal|meri\s+goal|my\s+goal|"
    r"mera\s+context|mera\s+profile|my\s+profile|"
    r"mera\s+data|meri\s+data|my\s+data|"
    r"mera\s+info|meri\s+info|my\s+info|"
    r"mere\s+facts|my\s+facts"
    r")\b",
    re.IGNORECASE,
)

# Memory keywords.
_MEMORY_COMMAND_RE = re.compile(
    r"\b("
    r"remember|forget|memor(y|ies)|"
    r"yaad\s+(rakh|rakho|rakhna|rakhlo|dila)|"
    r"bhool\s+(jao|ja|jana|jaao)|"
    r"bhul\s+(jao|ja|jana)|"
    r"clear\s+(all\s+)?memor|"
    r"(sab|sara)\s+bhool|"
    r"mere\s+baare\s+me|"
    r"about\s+me|"
    r"what\s+do\s+you\s+remember"
    r")\b",
    re.IGNORECASE,
)

# Action-on-the-computer signals — requires a specific target.
_OS_TARGET_RE = re.compile(
    r"\b("
    r"desktop|documents|downloads|pictures|music|videos|"
    r"my\s+pc|my\s+computer|my\s+desktop|"
    r"notepad|calculator|chrome|browser|vscode|vs\s+code|spotify|"
    r"folder|file|path|directory|"
    r"[A-Za-z]:\\|~/|%USERPROFILE%|%TEMP%"
    r")\b",
    re.IGNORECASE,
)

# Task verbs (ONLY when combined with an OS target).
_TASK_VERB_RE = re.compile(
    r"\b(open|launch|start|run|execute|"
    r"list|read|write|create|delete|remove|copy|move|rename|find|search|"
    r"browse|download|upload|install|uninstall|screenshot|"
    r"click|type|press|kholo|chalao|banao|dhundo|band)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Classification:
    kind: str
    confidence: float
    reason: str
    memory_action: str = ""
    memory_target: str = ""
    memory_new_value: str = ""

    @property
    def is_task(self) -> bool:
        return self.kind == "task"

    @property
    def is_memory_command(self) -> bool:
        return self.kind == "memory_command"

    @property
    def is_chat(self) -> bool:
        return self.kind == "chat"


class Classifier:
    def __init__(
        self,
        provider: AIProvider,
        registry: ToolRegistry,
        model: str,
        *,
        cache=None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._model = model
        self._cache = cache

    # ------------------------------------------------------------------
    def classify(self, message: str) -> Classification:
        text = (message or "").strip()
        if not text:
            return Classification(kind="chat", confidence=1.0, reason="empty")

        # ---- 1. Fast path (LOCAL) ------------------------------------
        fast = self._fast_path(text)
        if fast is not None:
            log.info(
                "classifier: fast path",
                extra={"kind": fast.kind, "reason": fast.reason},
            )
            if self._cache is not None:
                try:
                    self._cache.put(
                        text,
                        kind=fast.kind,
                        confidence=fast.confidence,
                        reason=fast.reason,
                    )
                except Exception:
                    pass
            return fast

        # ---- 2. Cache lookup -----------------------------------------
        if self._cache is not None:
            try:
                cached = self._cache.get(text)
            except Exception:
                cached = None
            if cached is not None:
                log.info("classifier: cache hit", extra={"kind": cached.kind})
                return Classification(
                    kind=cached.kind,
                    confidence=cached.confidence,
                    reason=cached.reason or "cache",
                )

        # ---- 3. LLM (slow path) --------------------------------------
        tools_summary = [
            {"tool_id": s.tool_id, "description": s.description}
            for s in self._registry.list_specs()
        ]
        prompt = json.dumps(
            {"message": text, "available_tools": tools_summary},
            ensure_ascii=False,
            indent=2,
        )

        request = ChatRequest(
            model=self._model,
            messages=(
                ChatMessage(role=Role.SYSTEM, content=_SYSTEM),
                ChatMessage(role=Role.USER, content=prompt),
            ),
            temperature=0.0,
        )

        try:
            raw = self._provider.generate_structured(request, _SCHEMA)
        except ProviderError as exc:
            log.warning("classifier: provider error: %s", exc)
            return _fallback("provider error")
        except Exception as exc:
            log.exception("classifier: unexpected error")
            return _fallback(f"{type(exc).__name__}")

        errors = validate(_SCHEMA, raw)
        if errors:
            log.warning("classifier: schema invalid: %s", "; ".join(errors[:3]))
            return _fallback("schema error")

        kind = str(raw.get("kind", "")).strip().lower()
        if kind not in ("chat", "task", "memory_command"):
            return _fallback("invalid kind")

        try:
            confidence = float(raw.get("confidence", 0.75))
        except (TypeError, ValueError):
            confidence = 0.75

        reason = str(raw.get("reason", "")).strip()

        memory_action = ""
        memory_target = ""
        memory_new_value = ""
        if kind == "memory_command":
            memory_action = str(raw.get("memory_action", "")).strip().lower()
            if memory_action not in ("remember", "forget", "update", "list", "clear"):
                memory_action = _infer_action(text)
            memory_target = str(raw.get("memory_target", "")).strip()
            memory_new_value = str(raw.get("memory_new_value", "")).strip()

        log.info(
            "classifier: llm result",
            extra={
                "kind": kind,
                "confidence": confidence,
                "reason": reason,
                "action": memory_action,
                "target": memory_target,
            },
        )

        result = Classification(
            kind=kind,
            confidence=confidence,
            reason=reason,
            memory_action=memory_action,
            memory_target=memory_target,
            memory_new_value=memory_new_value,
        )

        if self._cache is not None:
            try:
                self._cache.put(
                    text,
                    kind=result.kind,
                    confidence=result.confidence,
                    reason=result.reason,
                )
            except Exception:
                pass

        return result

    # ------------------------------------------------------------------
    def _fast_path(self, text: str) -> Optional[Classification]:
        s = text.strip()

        # ---- Memory command: keyword match ----
        if _MEMORY_COMMAND_RE.search(s):
            action = _infer_action(s)
            target = _infer_target(s)
            if action == "remember":
                return None
            return Classification(
                kind="memory_command",
                confidence=0.9,
                reason="memory keyword",
                memory_action=action,
                memory_target=target,
            )

        # ---- Memory command: user attribute + action ----
        if _USER_ATTR_RE.search(s):
            action = _infer_action(s)
            if action in ("forget", "update", "remember"):
                target = _infer_target(s) or _extract_user_target(s)
                if action == "remember" and not target:
                    return None
                return Classification(
                    kind="memory_command",
                    confidence=0.85,
                    reason="user attribute + action",
                    memory_action=action,
                    memory_target=target,
                    memory_new_value=_extract_update_value(s) if action == "update" else "",
                )

        # ---- Greetings / short ----
        if _GREETING_RE.match(s):
            return Classification(kind="chat", confidence=0.99, reason="greeting")

        if len(s) <= 3:
            return Classification(kind="chat", confidence=0.95, reason="short")

        # ---- Chat-intent keywords (code / explain / how-to) ----
        # These override task verbs: e.g. "list of features" is chat.
        if _CHAT_INTENT_RE.search(s):
            # But if there is ALSO an OS target with a task verb, it's a task.
            if _TASK_VERB_RE.search(s) and _OS_TARGET_RE.search(s):
                return Classification(
                    kind="task",
                    confidence=0.8,
                    reason="chat intent + os target",
                )
            return Classification(
                kind="chat",
                confidence=0.9,
                reason="chat intent keyword",
            )

        # ---- Task: task verb + OS target ----
        if _TASK_VERB_RE.search(s) and _OS_TARGET_RE.search(s):
            return Classification(kind="task", confidence=0.9, reason="task verb + os target")

        # ---- Task verb at the start (loose) ----
        first_word = s.split(maxsplit=1)[0].rstrip(".,!?:;")
        if _TASK_VERB_RE.fullmatch(first_word) and _OS_TARGET_RE.search(s):
            return Classification(kind="task", confidence=0.8, reason="task verb start + os")

        # ---- Short questions → chat ----
        if _SHORT_QUESTION_RE.match(s) and len(s.split()) <= 12:
            if not (_TASK_VERB_RE.search(s) and _OS_TARGET_RE.search(s)):
                return Classification(kind="chat", confidence=0.85, reason="short question")

        # ---- Fallback: not sure → chat (safer than task) ----
        return None


# ----------------------------------------------------------------------
def _fallback(reason: str) -> Classification:
    log.info("classifier: falling back to chat", extra={"reason": reason})
    return Classification(kind="chat", confidence=0.0, reason=f"fallback: {reason}")


def _infer_action(text: str) -> str:
    low = text.lower()
    if any(k in low for k in (
        "clear", "sab bhool", "sab bhul", "forget everything",
        "forget all", "delete all", "clear all",
    )):
        return "clear"
    if any(k in low for k in (
        "list", "show", "dikhao", "batao", "what do you remember",
        "mere baare me", "mere bare me", "about me",
    )):
        return "list"
    if any(k in low for k in (
        "change", "update", "badlo", "badal", "now",
    )):
        return "update"
    if any(k in low for k in (
        "forget", "bhool", "bhul", "delete", "remove", "hatao", "hata",
        "mitao", "mita", "nikalo", "nikal",
    )):
        return "forget"
    if any(k in low for k in (
        "remember", "yaad rakh", "note", "store",
    )):
        return "remember"
    return "remember"


def _infer_target(text: str) -> str:
    low = text.lower()
    for hint in ("mera naam", "meri identity", "mera name", "my name"):
        if hint in low:
            return "my name"
    for hint in (
        "my favourite colour", "favourite colour", "pasand colour",
        "mera pasand", "prefer",
    ):
        if hint in low:
            return "preference"
    return ""


def _extract_user_target(text: str) -> str:
    low = text.lower()
    import re as _re
    for pattern in (
        r"\b(\w{3,})\s+ko\s+(?:delete|remove|hata|bhool|forget)",
        r"\b(?:delete|remove|hata|bhool|forget|mita)\s+(\w{3,})",
    ):
        m = _re.search(pattern, low)
        if m:
            candidate = m.group(1)
            if candidate not in ("mera", "meri", "mere", "my", "the", "kar", "karo"):
                return candidate
    return ""


def _extract_update_value(text: str) -> str:
    import re as _re
    low = text.lower()
    for pattern in (
        r"\bto\s+(.+?)\s*$",
        r"\bkar\s+do\s*$",
        r"\bbana\s+do\s*$",
    ):
        m = _re.search(pattern, low)
        if m:
            candidate = m.group(1).strip().strip('"').strip("'").rstrip(".").strip()
            if candidate:
                return candidate
    return ""