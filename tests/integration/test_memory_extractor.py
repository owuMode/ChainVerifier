# tests/integration/test_memory_extractor.py
"""
Tests for MemoryExtractor and build_memory_block.
"""

from __future__ import annotations

from pathlib import Path

import pytest


class _FakeProvider:
    def __init__(self, result=None, raise_exc=False):
        self._result = result or {"memories": []}
        self._raise = raise_exc
        self.calls = 0

    def chat(self, request):
        raise NotImplementedError

    def stream(self, request):
        raise NotImplementedError

    def generate_structured(self, request, schema):
        self.calls += 1
        if self._raise:
            raise RuntimeError("boom")
        return self._result

    def get_models(self):
        return ()

    def validate_connection(self):
        return None

    def close(self):
        return None


def _prompts():
    from prompts.manager import PromptManager
    return PromptManager(Path(__file__).resolve().parents[2] / "prompts")


def test_extractor_returns_candidates():
    from memory.extractor import MemoryExtractor

    provider = _FakeProvider(result={
        "memories": [
            {"kind": "identity", "content": "User's name is Siyak.",
             "importance": 5, "confidence": 0.95, "tags": ["name"]},
            {"kind": "preference", "content": "User prefers Hinglish.",
             "importance": 4, "confidence": 0.85},
        ],
    })
    ex = MemoryExtractor(provider, _prompts())

    result = ex.extract(
        messages=[
            {"role": "user", "content": "Hi, I'm Siyak. Reply in Hinglish please."},
            {"role": "assistant", "content": "Got it."},
        ],
        model="test",
    )

    assert len(result) == 2
    kinds = {r.kind for r in result}
    assert "identity" in kinds
    assert "preference" in kinds


def test_extractor_filters_short_content():
    from memory.extractor import MemoryExtractor

    provider = _FakeProvider(result={
        "memories": [
            {"kind": "fact", "content": "hi", "importance": 3, "confidence": 0.9},
        ],
    })
    ex = MemoryExtractor(provider, _prompts())

    result = ex.extract(messages=[{"role": "user", "content": "hi"}], model="test")
    assert result == []


def test_extractor_never_raises():
    from memory.extractor import MemoryExtractor

    provider = _FakeProvider(raise_exc=True)
    ex = MemoryExtractor(provider, _prompts())

    result = ex.extract(messages=[{"role": "user", "content": "hello world"}], model="test")
    assert result == []


def test_extractor_empty_messages():
    from memory.extractor import MemoryExtractor

    provider = _FakeProvider()
    ex = MemoryExtractor(provider, _prompts())

    assert ex.extract(messages=[], model="test") == []
    assert provider.calls == 0


def test_build_memory_block():
    from memory.injector import build_memory_block
    from memory.repositories import Memory

    mems = [
        Memory(memory_id="1", user_id="default", kind="identity",
               content="User's name is Siyak.", importance=5, created_at="2026-10-01"),
        Memory(memory_id="2", user_id="default", kind="preference",
               content="User prefers Hinglish.", importance=4, created_at="2026-10-01"),
    ]
    block = build_memory_block(mems)
    assert "What I remember about you" in block
    assert "User's name is Siyak." in block
    assert "Hinglish" in block


def test_build_memory_block_empty():
    from memory.injector import build_memory_block
    assert build_memory_block([]) == ""


def test_inject_into_system_prompt():
    from memory.injector import inject_into_system_prompt

    sys_prompt = "You are Rhea."
    block = "## What I remember about you\n- Identity\n  - User's name is Siyak."

    combined = inject_into_system_prompt(sys_prompt, block)
    assert sys_prompt in combined
    assert "User's name is Siyak." in combined

    # Empty block returns sys prompt unchanged.
    assert inject_into_system_prompt(sys_prompt, "") == sys_prompt