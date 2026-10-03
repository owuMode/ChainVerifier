# memory/policies.py
"""
Memory policies — decision helpers for the memory subsystem.

Pure functions. No side effects. No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


# ----------------------------------------------------------------------
# Limits
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class MemoryLimits:
    # Extraction
    min_messages_for_extraction: int = 2
    min_confidence_to_store: float = 0.55
    min_content_length: int = 8
    max_content_length: int = 2000
    max_extracted_per_turn: int = 5

    # Retrieval
    recall_top_k: int = 5
    recall_min_score: float = 0.0

    # Retention
    default_ttl_days: Optional[int] = None
    temporary_ttl_hours: int = 24

    # Embeddings (Phase 4d)
    embeddings_enabled: bool = True
    embedding_batch_size: int = 32
    vector_top_k: int = 20
    keyword_top_k: int = 20
    min_vector_score: float = 0.35
    hybrid_weight_vector: float = 0.7
    hybrid_weight_keyword: float = 0.3


DEFAULT_LIMITS = MemoryLimits()


# ----------------------------------------------------------------------
# Decision helpers
# ----------------------------------------------------------------------
def should_extract(
    *,
    message_count: int,
    limits: MemoryLimits = DEFAULT_LIMITS,
) -> bool:
    return message_count >= limits.min_messages_for_extraction


def is_worth_storing(
    *,
    content: str,
    confidence: float,
    limits: MemoryLimits = DEFAULT_LIMITS,
) -> bool:
    if not content:
        return False
    text = content.strip()
    if len(text) < limits.min_content_length:
        return False
    if len(text) > limits.max_content_length:
        return False
    if confidence < limits.min_confidence_to_store:
        return False
    return True


def importance_to_confidence(importance: int) -> float:
    importance = max(1, min(5, int(importance)))
    return {1: 0.55, 2: 0.65, 3: 0.75, 4: 0.85, 5: 0.95}[importance]


# ----------------------------------------------------------------------
# Expiry helpers
# ----------------------------------------------------------------------
def expiry_for(kind: str, *, now: Optional[datetime] = None) -> Optional[str]:
    return None


def expiry_in_hours(hours: int, *, now: Optional[datetime] = None) -> str:
    base = now or datetime.now(timezone.utc)
    return (base + timedelta(hours=int(hours))).isoformat()


def expiry_in_days(days: int, *, now: Optional[datetime] = None) -> str:
    base = now or datetime.now(timezone.utc)
    return (base + timedelta(days=int(days))).isoformat()