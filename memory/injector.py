# memory/injector.py
"""
MemoryInjector — build the memory block inserted into system prompts.

Takes a list of Memory objects (already retrieved by MemoryManager)
and produces a compact block of text that is prepended to the
system prompt for chat and agent flows.

Design:
  * Deterministic format — no LLM here.
  * Groups by kind for readability.
  * Respects a token budget (approximate: characters / 4).
  * Returns "" if there are no memories.
"""

from __future__ import annotations

from memory.repositories import Memory


# Approximate character budget for the memory block.
DEFAULT_MAX_CHARS = 1200

_KIND_ORDER = (
    "identity",
    "preference",
    "goal",
    "context",
    "relationship",
    "skill",
    "habit",
    "constraint",
    "interest",
    "opinion",
    "event",
    "fact",
    "other",
)

_KIND_LABEL = {
    "identity":     "Identity",
    "preference":   "Preferences",
    "goal":         "Goals",
    "context":      "Current context",
    "relationship": "Relationships",
    "skill":        "Skills",
    "habit":        "Habits",
    "constraint":   "Constraints",
    "interest":     "Interests",
    "opinion":      "Opinions",
    "event":        "Events",
    "fact":         "Facts",
    "other":        "Other",
}


def build_memory_block(
    memories: list[Memory],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """
    Return a formatted block of memories, or "" if there are none.

    The block is meant to be prepended to a system prompt, e.g.:

        You are Rhea...

        ## What I remember about you
        - Identity
          - User's name is Siyak.
          - User lives in India (IST).
        - Preferences
          - User prefers responses in Hinglish.

    Every fact is listed once. Ordering within a kind is by importance
    descending.
    """
    if not memories:
        return ""

    grouped: dict[str, list[Memory]] = {}
    for m in memories:
        grouped.setdefault(m.kind, []).append(m)

    # Sort memories within each kind by importance desc.
    for kind in grouped:
        grouped[kind].sort(key=lambda m: (m.importance, m.created_at), reverse=True)

    lines: list[str] = ["## What I remember about you"]

    total = len(lines[0])
    for kind in _KIND_ORDER:
        items = grouped.get(kind)
        if not items:
            continue

        label = _KIND_LABEL.get(kind, kind.title())
        header = f"- {label}"
        if total + len(header) > max_chars:
            break
        lines.append(header)
        total += len(header) + 1

        for m in items:
            bullet = f"  - {m.content.strip()}"
            if total + len(bullet) > max_chars:
                return "\n".join(lines)
            lines.append(bullet)
            total += len(bullet) + 1

    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def inject_into_system_prompt(system_prompt: str, memory_block: str) -> str:
    """
    Combine an existing system prompt with the memory block.

    The memory block is appended after the system prompt, separated by
    a blank line. If the block is empty, the system prompt is returned
    unchanged.
    """
    if not memory_block:
        return system_prompt
    return f"{system_prompt}\n\n{memory_block}"