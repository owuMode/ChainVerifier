# memory/explicit.py
"""
Explicit memory commands — parse "remember X" / "forget X" / "change X to Y".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ExplicitKind(str, Enum):
    REMEMBER = "remember"
    FORGET = "forget"
    UPDATE = "update"
    LIST = "list"
    CLEAR = "clear"


@dataclass(frozen=True)
class ExplicitCommand:
    kind: ExplicitKind
    content: str = ""
    memory_kind: str = "fact"
    new_content: str = ""


# ----------------------------------------------------------------------
# Patterns
# ----------------------------------------------------------------------
_REMEMBER_PATTERNS = [
    re.compile(r"^\s*remember\s+(?:that\s+)?(.+?)\s*$", re.IGNORECASE),
    re.compile(r"^\s*note\s+(?:that\s+)?(.+?)\s*$", re.IGNORECASE),
    re.compile(r"^\s*please\s+remember\s+(?:that\s+)?(.+?)\s*$", re.IGNORECASE),
    re.compile(r"^\s*yaad\s+rakh(?:na|o|lo)?\s+(?:ki\s+)?(.+?)\s*$", re.IGNORECASE),
    re.compile(r"^\s*yaad\s+rakhna\s+(.+?)\s*$", re.IGNORECASE),
]

_UPDATE_PATTERNS = [
    # "change my name to Siyak"
    re.compile(
        r"^\s*(?:change|update|set|badlo|badal\s+do)\s+(?:my\s+)?(.+?)\s+to\s+(.+?)\s*$",
        re.IGNORECASE,
    ),
    # "update the memory about my name to Siyak"
    re.compile(
        r"^\s*(?:update|change|edit)\s+(?:the\s+)?memor(?:y|ies)\s+(?:about\s+)?(.+?)\s+to\s+(.+?)\s*$",
        re.IGNORECASE,
    ),
    # "my name is now Siyak"  (identity update)
    re.compile(
        r"^\s*my\s+name\s+is\s+now\s+(.+?)\s*$",
        re.IGNORECASE,
    ),
]

_FORGET_PATTERNS = [
    re.compile(r"^\s*forget\s+(?:that\s+)?(.+?)\s*$", re.IGNORECASE),
    re.compile(r"^\s*forget\s+about\s+(.+?)\s*$", re.IGNORECASE),
    re.compile(r"^\s*bhool\s+(?:jao\s+)?(?:ki\s+)?(.+?)\s*$", re.IGNORECASE),
    re.compile(r"^\s*bhul\s+(?:jao\s+)?(?:ki\s+)?(.+?)\s*$", re.IGNORECASE),
]

_LIST_PATTERNS = [
    re.compile(r"^\s*(?:what|kya)\s+(?:do\s+you\s+)?remember", re.IGNORECASE),
    re.compile(r"^\s*(?:show|list|dikhao|batao)\s+(?:my\s+)?memor(?:y|ies)", re.IGNORECASE),
    re.compile(r"^\s*(?:my\s+)?memories\s*\??\s*$", re.IGNORECASE),
]

_CLEAR_PATTERNS = [
    re.compile(r"^\s*(?:forget|clear|delete)\s+(?:everything|all|sab)\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:clear|delete)\s+(?:all\s+)?memor(?:y|ies)\s*$", re.IGNORECASE),
    re.compile(r"^\s*bhool\s+(?:jao\s+)?sab\s*$", re.IGNORECASE),
    re.compile(r"^\s*bhul\s+(?:jao\s+)?sab\s*$", re.IGNORECASE),
    re.compile(r"^\s*sab\s+bhool\s+jao\s*$", re.IGNORECASE),
]


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
def parse(message: str) -> Optional[ExplicitCommand]:
    if not message:
        return None

    text = message.strip()
    if not text:
        return None

    # Order matters: specific first.

    for pat in _CLEAR_PATTERNS:
        if pat.match(text):
            return ExplicitCommand(kind=ExplicitKind.CLEAR)

    for pat in _LIST_PATTERNS:
        if pat.match(text):
            return ExplicitCommand(kind=ExplicitKind.LIST)

    for pat in _UPDATE_PATTERNS:
        m = pat.match(text)
        if m:
            groups = m.groups()
            if len(groups) == 2:
                old = groups[0].strip().strip('"').strip("'").rstrip(".").strip()
                new = groups[1].strip().strip('"').strip("'").rstrip(".").strip()
            else:
                # "my name is now X"
                old = "name"
                new = groups[0].strip().strip('"').strip("'").rstrip(".").strip()
            if old and new:
                return ExplicitCommand(
                    kind=ExplicitKind.UPDATE,
                    content=old,
                    new_content=new,
                )

    for pat in _REMEMBER_PATTERNS:
        m = pat.match(text)
        if m:
            content = m.group(1).strip().strip('"').strip("'").rstrip(".").strip()
            if content:
                return ExplicitCommand(
                    kind=ExplicitKind.REMEMBER,
                    content=content,
                    memory_kind=_infer_kind(content),
                )

    for pat in _FORGET_PATTERNS:
        m = pat.match(text)
        if m:
            content = m.group(1).strip().strip('"').strip("'").rstrip(".").strip()
            if content:
                if content.lower() in ("sab", "everything", "all"):
                    return ExplicitCommand(kind=ExplicitKind.CLEAR)
                return ExplicitCommand(kind=ExplicitKind.FORGET, content=content)

    return None


# ----------------------------------------------------------------------
# Kind inference
# ----------------------------------------------------------------------
_KIND_HINTS = (
    ("preference", (
        "i like", "i love", "i prefer", "i hate", "i dislike",
        "pasand", "nafrat", "favourite", "favorite",
        "hinglish", "reply in", "respond in",
    )),
    ("identity", (
        "my name", "mera naam", "i am", "i'm called",
        "main ", "mai ",
    )),
    ("goal", (
        "i want to", "my goal", "i'm working on", "i plan to",
        "mera goal", "karna chahta", "banane wala",
    )),
    ("relationship", (
        "my wife", "my husband", "my son", "my daughter",
        "my friend", "my boss", "my mother", "my father",
        "meri", "mera bhai", "meri behen",
    )),
    ("habit", (
        "every day", "always", "usually", "roz", "har din",
        "har roz",
    )),
    ("constraint", (
        "i can't", "i cannot", "i don't have", "nahi kar sakta",
        "mujhe nahi",
    )),
    ("skill", (
        "i know", "i'm good at", "i'm learning", "seekh raha",
        "sikh raha",
    )),
    ("interest", (
        "i'm interested in", "i'm into", "interested in",
        "shauk",
    )),
    ("event", (
        "my birthday", "anniversary", "wedding", "birthday",
        "shaadi",
    )),
)


def _infer_kind(content: str) -> str:
    low = content.lower()
    for kind, hints in _KIND_HINTS:
        for hint in hints:
            if hint in low:
                return kind
    return "fact"