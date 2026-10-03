# providers/base/models.py
"""
Normalized internal message models (spec §14, §65).

Rules:
  * Every provider adapter converts its wire format to these models.
  * Agent Core only ever sees these models.
  * Provider-specific fields (OpenAI's `finish_reason`, Anthropic's
    `stop_reason`, ...) are normalized into `finish_reason` here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class FinishReason(str, Enum):
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ToolCall:
    """A structured tool call as emitted by the model."""
    call_id: str
    tool_id: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: Optional[str] = None       # for Role.TOOL responses
    name: Optional[str] = None               # optional tool name for Role.TOOL


@dataclass(frozen=True)
class ChatRequest:
    model: str
    messages: tuple[ChatMessage, ...]
    temperature: float = 0.0
    max_output_tokens: Optional[int] = None
    tools: tuple[dict[str, Any], ...] = ()
    stream: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class ChatResponse:
    content: str
    finish_reason: FinishReason
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    provider: str = ""
    raw_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StreamChunk:
    """One chunk of a streaming response."""
    delta_text: str = ""
    tool_call_delta: Optional[dict[str, Any]] = None
    finish_reason: Optional[FinishReason] = None
    done: bool = False