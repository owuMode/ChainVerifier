# tests/integration/test_synthesizer.py
"""
Smoke tests for the answer Synthesizer.
"""

from __future__ import annotations

from pathlib import Path

import pytest


class _FakeProvider:
    def __init__(self, reply="Synthesized answer.", raise_exc=False):
        self._reply = reply
        self._raise = raise_exc
        self.calls = 0

    def chat(self, request):
        from providers.base.models import ChatResponse, FinishReason
        self.calls += 1
        if self._raise:
            raise RuntimeError("boom")
        return ChatResponse(
            content=self._reply,
            finish_reason=FinishReason.STOP,
            model=request.model,
            provider="fake",
        )

    def stream(self, request):
        raise NotImplementedError

    def generate_structured(self, request, schema):
        raise NotImplementedError

    def get_models(self):
        return ()

    def validate_connection(self):
        return None

    def close(self):
        return None


def _prompts():
    from prompts.manager import PromptManager
    return PromptManager(Path(__file__).resolve().parents[2] / "prompts")


def test_synthesizer_returns_llm_reply():
    from core.agent.synthesizer import Synthesizer, StepResult

    provider = _FakeProvider(reply="Aaj 2 October 2026 hai.")
    syn = Synthesizer(provider, _prompts())

    result = syn.synthesize(
        goal="aaj date kya h",
        step_results=[
            StepResult(
                tool_id="datetime",
                arguments={},
                output={"date": "2026-10-02"},
                verified=True,
            ),
        ],
        model="test",
    )

    assert result == "Aaj 2 October 2026 hai."
    assert provider.calls == 1


def test_synthesizer_falls_back_on_provider_error():
    from core.agent.synthesizer import Synthesizer, StepResult

    provider = _FakeProvider(raise_exc=True)
    syn = Synthesizer(provider, _prompts())

    result = syn.synthesize(
        goal="x",
        step_results=[
            StepResult(tool_id="datetime", arguments={}, output={}, verified=True),
        ],
        model="test",
    )

    assert "datetime" in result


def test_synthesizer_handles_empty_results():
    from core.agent.synthesizer import Synthesizer

    provider = _FakeProvider()
    syn = Synthesizer(provider, _prompts())

    result = syn.synthesize(goal="x", step_results=[], model="test")
    assert result
    assert "couldn't" in result.lower() or "could not" in result.lower()