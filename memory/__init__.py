# memory/__init__.py
"""
Memory package — long-term memory for the agent (spec §41).
"""

from memory.cache import (
    CachedClassification,
    CachedEmbedding,
    ClassifierCache,
    EmbeddingCache,
)
from memory.consolidator import (
    MemoryConsolidator,
    MergeGroup,
    MergeResult,
)
from memory.embeddings import (
    EmbeddedVector,
    EmbeddingService,
    cosine_similarity,
    from_blob,
    to_blob,
)
from memory.explicit import (
    ExplicitCommand,
    ExplicitKind,
    parse as parse_explicit,
)
from memory.extractor import ExtractedMemory, MemoryExtractor
from memory.injector import build_memory_block, inject_into_system_prompt
from memory.manager import MemoryManager, RankedMemory
from memory.novelty import is_worth_extracting, new_tokens, tokenize
from memory.policies import (
    DEFAULT_LIMITS,
    MemoryLimits,
    expiry_in_days,
    expiry_in_hours,
    is_worth_storing,
    should_extract,
)
from memory.repositories import (
    ALLOWED_KINDS,
    ALLOWED_SOURCES,
    Memory,
    MemoryRepository,
)

__all__ = [
    "MemoryManager",
    "MemoryRepository",
    "Memory",
    "MemoryLimits",
    "DEFAULT_LIMITS",
    "ALLOWED_KINDS",
    "ALLOWED_SOURCES",
    "is_worth_storing",
    "should_extract",
    "expiry_in_hours",
    "expiry_in_days",
    "MemoryExtractor",
    "ExtractedMemory",
    "build_memory_block",
    "inject_into_system_prompt",
    "ExplicitCommand",
    "ExplicitKind",
    "parse_explicit",
    "EmbeddingService",
    "EmbeddedVector",
    "RankedMemory",
    "cosine_similarity",
    "to_blob",
    "from_blob",
    "EmbeddingCache",
    "ClassifierCache",
    "CachedEmbedding",
    "CachedClassification",
    "is_worth_extracting",
    "new_tokens",
    "tokenize",
    "MemoryConsolidator",
    "MergeGroup",
    "MergeResult",
]