# providers/base/capabilities.py
"""
Capability abstraction (spec §15).

Different providers/models support different features. Before the agent
uses a feature, it MUST verify it is available:

    check provider → check model → check capability → use feature

Never assume all models are equivalent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Capability(str, Enum):
    TOOL_CALLING = "tool_calling"
    STRUCTURED_OUTPUT = "structured_output"
    VISION = "vision"
    AUDIO = "audio"
    STREAMING = "streaming"
    LONG_CONTEXT = "long_context"
    REASONING = "reasoning"


@dataclass(frozen=True)
class ModelCapabilities:
    """Declared capabilities of a specific model."""
    model_id: str
    capabilities: frozenset[Capability] = field(default_factory=frozenset)
    context_window: int = 0
    max_output_tokens: int = 0

    def has(self, capability: Capability) -> bool:
        return capability in self.capabilities

    def supports_all(self, *caps: Capability) -> bool:
        return all(self.has(c) for c in caps)

    def supports_any(self, *caps: Capability) -> bool:
        return any(self.has(c) for c in caps)