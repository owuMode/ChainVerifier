# tests/unit/test_prompt_manager.py
"""
PromptManager — load, cache, versions, missing-file behaviour.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from prompts.manager import PromptManager, PromptNotFoundError


def _prompts_root() -> Path:
    return Path(__file__).resolve().parents[2] / "prompts"


def test_load_existing_prompt():
    pm = PromptManager(_prompts_root())
    prompt = pm.get("system/system")
    assert prompt.name == "system/system"
    assert prompt.version == "latest"
    assert "AIProduct" in prompt.text
    assert prompt.path.name == "system.md"


def test_load_planner_prompt():
    pm = PromptManager(_prompts_root())
    prompt = pm.get("agent/planner")
    assert "planner" in prompt.text.lower()
    assert "steps" in prompt.text.lower()


def test_cache_returns_same_object():
    pm = PromptManager(_prompts_root())
    a = pm.get("system/system")
    b = pm.get("system/system")
    assert a is b


def test_missing_prompt_raises():
    pm = PromptManager(_prompts_root())
    with pytest.raises(PromptNotFoundError):
        pm.get("nonexistent/nope")


def test_missing_version_raises():
    pm = PromptManager(_prompts_root())
    with pytest.raises(PromptNotFoundError):
        pm.get("system/system", version="does_not_exist")


def test_exists_true_and_false():
    pm = PromptManager(_prompts_root())
    assert pm.exists("system/system")
    assert not pm.exists("nope/nope")


def test_list_versions_includes_latest():
    pm = PromptManager(_prompts_root())
    versions = pm.list_versions("system/system")
    assert "latest" in versions


def test_list_versions_unknown_prompt_is_empty():
    pm = PromptManager(_prompts_root())
    assert pm.list_versions("nope/nope") == []


def test_invalid_root_raises(tmp_path: Path):
    with pytest.raises(PromptNotFoundError):
        PromptManager(tmp_path / "not-a-folder")


def test_dot_notation_alias():
    pm = PromptManager(_prompts_root())
    a = pm.get("agent/planner")
    b = pm.get("agent.planner")
    assert a.text == b.text