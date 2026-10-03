# tests/unit/test_providers_models.py
from providers.base.capabilities import Capability, ModelCapabilities
from providers.base.models import (
    ChatMessage,
    ChatRequest,
    FinishReason,
    Role,
    StreamChunk,
    ToolCall,
    Usage,
)


def test_capabilities_membership():
    caps = ModelCapabilities(
        model_id="m",
        capabilities=frozenset({Capability.STREAMING, Capability.TOOL_CALLING}),
    )
    assert caps.has(Capability.STREAMING)
    assert not caps.has(Capability.VISION)
    assert caps.supports_all(Capability.STREAMING, Capability.TOOL_CALLING)
    assert caps.supports_any(Capability.VISION, Capability.STREAMING)
    assert not caps.supports_all(Capability.STREAMING, Capability.VISION)


def test_chat_message_roles():
    msg = ChatMessage(role=Role.USER, content="hi")
    assert msg.role is Role.USER
    assert msg.content == "hi"


def test_tool_call_message():
    tc = ToolCall(call_id="c1", tool_id="test_tool", arguments={"message": "hi"})
    msg = ChatMessage(role=Role.ASSISTANT, tool_calls=(tc,))
    assert msg.tool_calls[0].tool_id == "test_tool"


def test_chat_request_defaults():
    req = ChatRequest(model="m", messages=())
    assert req.temperature == 0.0
    assert req.stream is False
    assert req.tools == ()


def test_usage_and_finish_reason():
    u = Usage(prompt_tokens=1, completion_tokens=2, total_tokens=3)
    assert u.total_tokens == 3
    assert FinishReason.STOP.value == "stop"


def test_stream_chunk_defaults():
    c = StreamChunk()
    assert c.delta_text == ""
    assert c.done is False