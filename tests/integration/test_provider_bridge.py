# tests/integration/test_provider_bridge.py
"""
Smoke tests for ProviderBridge.

Phase 3: setActiveProvider now requires the provider to have an API
key. Tests that switch active providers must first set a key.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture(scope="module", autouse=True)
def _offscreen_qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    yield


@pytest.fixture
def bridge(tmp_path: Path):
    from config.configuration_service import ConfigurationService
    from providers.base.models import (
        ChatRequest,
        ChatResponse,
        FinishReason,
        StreamChunk,
    )
    from providers.base.provider import AIProvider
    from providers.manager import ProviderManager
    from security.secrets import Secrets

    defaults = (
        Path(__file__).resolve().parents[2]
        / "config" / "defaults" / "defaults.yaml"
    )
    config = ConfigurationService(defaults)
    secrets = Secrets(tmp_path / "secrets")
    pm = ProviderManager()

    class _DummyProvider(AIProvider):
        provider_id = "openai_compatible"
        adapter_name = "openai_compatible"

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
            return {}

        def get_models(self):
            return ()

        def validate_connection(self) -> None:
            return None

    pm.register("openai_compatible", lambda: _DummyProvider())

    from gui.web.provider_bridge import ProviderBridge
    return ProviderBridge(config=config, secrets=secrets, provider_manager=pm)


def test_list_providers_returns_presets(bridge):
    raw = bridge.listProvidersJson()
    rows = json.loads(raw)
    assert isinstance(rows, list)
    assert any(p["key"] == "openai" for p in rows)
    assert any(p["key"] == "gemini" for p in rows)


def test_has_api_key_false_by_default(bridge):
    assert bridge.hasApiKey("openai") is False


def test_set_and_has_api_key(bridge):
    ok = bridge.setApiKey("openai", "sk-test-not-real-1234")
    assert ok is True
    assert bridge.hasApiKey("openai") is True


def test_masked_key_does_not_reveal_full(bridge):
    bridge.setApiKey("openai", "sk-test-not-real-1234")
    masked = bridge.getMaskedApiKey("openai")
    assert "sk-test-not-real-1234" not in masked
    assert masked.endswith("1234")


def test_delete_api_key(bridge):
    bridge.setApiKey("openai", "sk-test-not-real-1234")
    assert bridge.deleteApiKey("openai") is True
    assert bridge.hasApiKey("openai") is False


def test_set_active_provider(bridge):
    # Must have an API key first.
    bridge.setApiKey("gemini", "AIza-test-not-real-key-1234")
    assert bridge.setActiveProvider("gemini") is True
    raw = bridge.getActiveProviderJson()
    obj = json.loads(raw)
    assert obj["key"] == "gemini"


def test_set_active_provider_rejects_unknown(bridge):
    assert bridge.setActiveProvider("nope") is False


def test_set_active_provider_requires_key(bridge):
    # Fresh provider without a key → rejected.
    assert bridge.setActiveProvider("openai") is False


def test_list_models_for_gemini(bridge):
    raw = bridge.listModelsJson("gemini")
    rows = json.loads(raw)
    assert isinstance(rows, list)
    assert len(rows) > 0
    assert any(m["is_default"] for m in rows)


def test_list_models_for_unknown_returns_empty(bridge):
    assert bridge.listModelsJson("nope") == "[]"


def test_set_and_get_current_model(bridge):
    bridge.setApiKey("openai", "sk-test-not-real-1234")
    bridge.setActiveProvider("openai")
    bridge.setCurrentModel("gpt-4o")
    assert bridge.getCurrentModel() == "gpt-4o"


def test_get_current_model_falls_back_to_default_for_wrong_provider(bridge):
    """
    If the stored model does not belong to the active provider, the
    bridge returns the active provider's default.
    """
    # Ensure both providers have keys.
    bridge.setApiKey("openai", "sk-test-not-real-1234")
    bridge.setApiKey("gemini", "AIza-test-not-real-key-1234")

    bridge.setActiveProvider("openai")
    bridge.setCurrentModel("gpt-4o")  # valid for openai

    # Switch to gemini — gpt-4o is invalid there.
    bridge.setActiveProvider("gemini")
    result = bridge.getCurrentModel()

    # The active provider's default model is used.
    assert result != "gpt-4o"
    assert result  # non-empty (default model id)


def test_test_connection_without_key_reports_error(bridge):
    bridge.deleteApiKey("openai")
    raw = bridge.testConnection("openai")
    obj = json.loads(raw)
    assert obj["ok"] is False