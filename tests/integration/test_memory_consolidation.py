# tests/integration/test_memory_consolidation.py
"""
Tests for memory consolidation.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _migrations_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "database" / "migrations"


@pytest.fixture
def db(tmp_path: Path):
    from database.manager import DatabaseManager

    database = DatabaseManager(
        db_path=tmp_path / "app.sqlite",
        migrations_dir=_migrations_dir(),
    )
    database.open()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def repo(db):
    from memory.repositories import MemoryRepository
    return MemoryRepository(db)


class _ScriptedProvider:
    def __init__(self, merged_content="User is a big fan of coffee."):
        self._merged = merged_content

    def generate_structured(self, request, schema):
        return {
            "content": self._merged,
            "confidence": 0.9,
            "importance": 4,
            "reason": "merged",
        }

    def chat(self, request):
        raise NotImplementedError

    def stream(self, request):
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


def test_find_merge_groups_keyword(repo):
    from memory.consolidator import MemoryConsolidator
    from memory.repositories import Memory

    # Three similar memories.
    repo.create(Memory(memory_id="", user_id="default", kind="preference",
                       content="User likes coffee very much"))
    repo.create(Memory(memory_id="", user_id="default", kind="preference",
                       content="User likes coffee a lot"))
    # One unrelated.
    repo.create(Memory(memory_id="", user_id="default", kind="preference",
                       content="User prefers Hinglish replies"))

    consolidator = MemoryConsolidator(
        provider=_ScriptedProvider(),
        prompts=_prompts(),
        repo=repo,
    )

    all_mems = repo.list_recent(user_id="default", limit=100)
    groups = consolidator.find_merge_groups(all_mems)

    assert len(groups) == 1
    assert len(groups[0].memories) == 2


def test_merge_group_calls_llm(repo):
    from memory.consolidator import MemoryConsolidator, MergeGroup
    from memory.repositories import Memory

    m1 = repo.create(Memory(memory_id="", user_id="default", kind="preference",
                            content="User likes coffee"))
    m2 = repo.create(Memory(memory_id="", user_id="default", kind="preference",
                            content="User loves coffee"))

    consolidator = MemoryConsolidator(
        provider=_ScriptedProvider("User is a big coffee fan."),
        prompts=_prompts(),
        repo=repo,
    )

    group = MergeGroup(kind="preference", memories=[m1, m2])
    result = consolidator.merge_group(group, model="test")

    assert result is not None
    assert "coffee" in result.content.lower()
    assert result.importance == 4


def test_manager_consolidate_end_to_end(repo):
    from memory.consolidator import MemoryConsolidator
    from memory.manager import MemoryManager
    from memory.repositories import Memory

    # Three similar + one different.
    repo.create(Memory(memory_id="", user_id="default", kind="preference",
                       content="User likes coffee in the morning"))
    repo.create(Memory(memory_id="", user_id="default", kind="preference",
                       content="User likes coffee a lot"))
    repo.create(Memory(memory_id="", user_id="default", kind="preference",
                       content="User likes coffee very much"))
    repo.create(Memory(memory_id="", user_id="default", kind="preference",
                       content="User prefers Hinglish replies"))

    mgr = MemoryManager(repo)
    consolidator = MemoryConsolidator(
        provider=_ScriptedProvider("User is a big coffee fan."),
        prompts=_prompts(),
        repo=repo,
    )

    before = mgr.count()
    stats = mgr.consolidate(consolidator=consolidator, model="test")

    # At least one group should be found and merged.
    assert stats["groups_found"] >= 1
    assert stats["groups_merged"] >= 1
    assert stats["memories_archived"] >= 2
    assert stats["memories_created"] >= 1

    # Count may stay same or go down (originals archived, one new created).
    after = mgr.count()
    assert after <= before


def test_manager_consolidate_dry_run(repo):
    from memory.consolidator import MemoryConsolidator
    from memory.manager import MemoryManager
    from memory.repositories import Memory

    repo.create(Memory(memory_id="", user_id="default", kind="preference",
                       content="User likes coffee a lot"))
    repo.create(Memory(memory_id="", user_id="default", kind="preference",
                       content="User likes coffee very much"))

    mgr = MemoryManager(repo)
    consolidator = MemoryConsolidator(
        provider=_ScriptedProvider("User likes coffee."),
        prompts=_prompts(),
        repo=repo,
    )

    before = mgr.count()
    stats = mgr.consolidate(consolidator=consolidator, model="test", dry_run=True)

    assert stats["groups_found"] >= 1
    assert stats["groups_merged"] >= 1
    # No changes in dry-run.
    assert mgr.count() == before