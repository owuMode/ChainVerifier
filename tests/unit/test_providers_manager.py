# tests/unit/test_providers_manager.py
import pytest

from providers.base.capabilities import Capability, ModelCapabilities
from providers.base.models import ChatRequest, ChatResponse, FinishReason, StreamChunk
from providers.base.provider import AIProvider
from providers.manager import NoActiveProviderError, ProviderManager


class _FakeProvider(AIProvider):
    provider_id = "fake"
    adapter_name = "fake"

    def __init__(self) -> None:
        self.closed = False

    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content="ok",
            finish_reason=FinishReason.STOP,
            model=request.model,
            provider=self.provider_id,
        )

    def stream(self, request: ChatRequest):
        yield StreamChunk(done=True)

    def generate_structured(self, request: ChatRequest, schema: dict) -> dict:
        return {"ok": True}

    def get_models(self):
        return (
            ModelCapabilities(
                model_id="m1",
                capabilities=frozenset({Capability.STREAMING}),
            ),
        )

    def validate_connection(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def test_register_and_set_active():
    pm = ProviderManager()
    pm.register("fake", lambda: _FakeProvider())
    pm.set_active("fake")
    assert pm.active_id() == "fake"
    assert pm.active().provider_id == "fake"


def test_no_active_provider_raises():
    pm = ProviderManager()
    with pytest.raises(NoActiveProviderError):
        pm.active()


def test_unknown_provider_raises():
    pm = ProviderManager()
    with pytest.raises(ValueError):
        pm.set_active("nope")


def test_instance_cached():
    pm = ProviderManager()
    pm.register("fake", lambda: _FakeProvider())
    pm.set_active("fake")
    a = pm.active()
    b = pm.active()
    assert a is b


def test_capability_check_with_no_active():
    pm = ProviderManager()
    assert pm.supports(Capability.STREAMING) is False


def test_capability_check_with_active():
    pm = ProviderManager()
    pm.register("fake", lambda: _FakeProvider())
    pm.set_active("fake")
    assert pm.supports(Capability.STREAMING) is True
    assert pm.supports(Capability.VISION) is False


def test_close_all():
    pm = ProviderManager()
    pm.register("fake", lambda: _FakeProvider())
    pm.set_active("fake")
    inst = pm.active()
    pm.close()
    assert inst.closed is True